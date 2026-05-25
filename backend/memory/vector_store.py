import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from dotenv import load_dotenv
from .memory_manager import MemoryManager
from .json_store import JsonMemoryStore

load_dotenv()


class VectorMemoryStore(MemoryManager):

    def __init__(self):
        self._json = JsonMemoryStore()   # single shared JSON back-end instance
        self.db_enabled = os.getenv("DB_ENABLED", "false").lower() == "true"
        self.conn_params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", 5433)),
            "dbname": os.getenv("DB_NAME", "aicaeru"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", ""),
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "1")),
        }
        self._ensure_connection()

    # ------------------------------------------------------------------
    # PostgreSQL connection management
    # ------------------------------------------------------------------

    def _ensure_connection(self):
        if not self.db_enabled:
            self.conn = None
            return
        try:
            self.conn = psycopg2.connect(**self.conn_params)
            self.conn.autocommit = True
            print("PostgreSQL 連線成功！")
        except Exception as e:
            print(f"PostgreSQL 連線失敗：{e}")
            self.conn = None

    def _get_cursor(self):
        if not self.db_enabled:
            return None
        try:
            if self.conn is None or self.conn.closed:
                self._ensure_connection()
            return self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        except Exception as e:
            print(f"取得 cursor 失敗：{e}")
            return None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _to_pgvector_str(embedding: list) -> str:
        """Format a Python float list as a pgvector literal: '[1.0,2.0,...]'"""
        return "[" + ",".join(map(str, embedding)) + "]"

    # ------------------------------------------------------------------
    # MemoryManager interface — delegates to JSON store
    # ------------------------------------------------------------------

    def get_profile(self, elder_id: str) -> dict:
        return self._json.get_profile(elder_id)

    def save_conversation(self, elder_id: str, history: list) -> bool:
        return self._json.save_conversation(elder_id, history)

    def load_conversation(self, elder_id: str) -> list:
        return self._json.load_conversation(elder_id)

    def clear_conversation(self, elder_id: str) -> bool:
        return self._json.clear_conversation(elder_id)

    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        return self._json.get_recent_events(elder_id, limit)

    def get_recent_conversation_summary(self, elder_id: str, limit: int = 6) -> list:
        return self._json.get_recent_conversation_summary(elder_id, limit)

    def update_profile(self, elder_id: str, data: dict) -> bool:
        return self._json.update_profile(elder_id, data)

    def _save(self, elder_id: str, data: dict) -> bool:
        return self._json._save(elder_id, data)

    # ------------------------------------------------------------------
    # Dual-write: JSON + PostgreSQL
    # ------------------------------------------------------------------

    def add_event(self, elder_id: str, event: dict) -> bool:
        self._json.add_event(elder_id, event)

        cursor = self._get_cursor()
        if not cursor:
            return False
        try:
            cursor.execute(
                """
                INSERT INTO elder_memories
                    (elder_id, content, sentiment, importance, memory_type,
                     topic_tags, spoken_at, date, persona_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    elder_id,
                    event.get("event", ""),
                    event.get("sentiment", "neutral"),
                    event.get("importance", 0.3),
                    event.get("memory_type", "short"),
                    event.get("topic_tags", []),
                    event.get("spoken_at"),
                    event.get("date", datetime.now().strftime("%Y-%m-%d")),
                    event.get("persona_id", "ai"),
                ),
            )
            return True
        except Exception as e:
            print(f"寫入 PostgreSQL 失敗：{e}")
            return False

    # ------------------------------------------------------------------
    # Vector / importance queries (PostgreSQL)
    # ------------------------------------------------------------------

    def get_important_memories(
        self,
        elder_id: str,
        importance_threshold: float = 0.7,
        limit: int = 10,
        persona_id: str = None,
    ) -> list:
        cursor = self._get_cursor()
        if not cursor:
            return self._json.get_important_memories(elder_id, importance_threshold, limit)

        try:
            params: list = [elder_id, importance_threshold]
            persona_clause = ""
            if persona_id and persona_id != "ai":
                persona_clause = "AND (persona_id = %s OR persona_id IS NULL OR persona_id = 'ai')"
                params.append(persona_id)
            params.append(limit)

            cursor.execute(
                f"""
                SELECT content AS event, sentiment, importance,
                       memory_type, topic_tags, date
                FROM elder_memories
                WHERE elder_id = %s AND importance >= %s
                  {persona_clause}
                ORDER BY importance DESC, date DESC
                LIMIT %s
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"撈取重要記憶失敗：{e}")
            return []

    def search_similar_memories(
        self,
        elder_id: str,
        query_embedding: list,
        limit: int = 5,
        persona_id: str = None,
    ) -> list:
        cursor = self._get_cursor()
        if not cursor:
            return []

        try:
            emb_str = self._to_pgvector_str(query_embedding)
            params: list = [emb_str, elder_id]
            persona_clause = ""
            if persona_id and persona_id != "ai":
                persona_clause = "AND (persona_id = %s OR persona_id IS NULL OR persona_id = 'ai')"
                params.append(persona_id)
            params.append(limit)

            cursor.execute(
                f"""
                SELECT content AS event, sentiment, importance,
                       memory_type, topic_tags, date,
                       embedding <=> %s::vector AS distance
                FROM elder_memories
                WHERE elder_id = %s
                  AND embedding IS NOT NULL
                  {persona_clause}
                ORDER BY distance ASC
                LIMIT %s
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"向量搜尋失敗：{e}")
            return []

    def update_embedding(self, memory_id: int, embedding: list) -> bool:
        cursor = self._get_cursor()
        if not cursor:
            return False
        try:
            cursor.execute(
                "UPDATE elder_memories SET embedding = %s::vector WHERE id = %s",
                (self._to_pgvector_str(embedding), memory_id),
            )
            return True
        except Exception as e:
            print(f"更新向量失敗：{e}")
            return False
