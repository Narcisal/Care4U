import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from dotenv import load_dotenv
from .memory_manager import MemoryManager

load_dotenv()

class VectorMemoryStore(MemoryManager):

    def __init__(self):
        self.conn_params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", 5433)),
            "dbname": os.getenv("DB_NAME", "aicaeru"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "careU1234"),
        }
        self._ensure_connection()

    def _ensure_connection(self):
        try:
            self.conn = psycopg2.connect(**self.conn_params)
            self.conn.autocommit = True
            print("PostgreSQL 連線成功！")
        except Exception as e:
            print(f"PostgreSQL 連線失敗：{e}")
            self.conn = None

    def _get_cursor(self):
        try:
            if self.conn is None or self.conn.closed:
                self._ensure_connection()
            return self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        except Exception as e:
            print(f"取得 cursor 失敗：{e}")
            return None

    def get_profile(self, elder_id: str) -> dict:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore().get_profile(elder_id)

    def save_conversation(self, elder_id: str, history: list) -> bool:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore().save_conversation(elder_id, history)

    def load_conversation(self, elder_id: str) -> list:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore().load_conversation(elder_id)

    def clear_conversation(self, elder_id: str) -> bool:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore().clear_conversation(elder_id)

    def add_event(self, elder_id: str, event: dict) -> bool:
        from .json_store import JsonMemoryStore
        JsonMemoryStore().add_event(elder_id, event)

        cursor = self._get_cursor()
        if not cursor:
            return False
        try:
            cursor.execute("""
                INSERT INTO elder_memories
                (elder_id, content, sentiment, importance, memory_type,
                 topic_tags, spoken_at, date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                elder_id,
                event.get("event", ""),
                event.get("sentiment", "neutral"),
                event.get("importance", 0.3),
                event.get("memory_type", "short"),
                event.get("topic_tags", []),
                event.get("spoken_at"),
                event.get("date", datetime.now().strftime("%Y-%m-%d"))
            ))
            return True
        except Exception as e:
            print(f"寫入 PostgreSQL 失敗：{e}")
            return False

    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore().get_recent_events(elder_id, limit)

    def get_important_memories(self, elder_id: str,
                                importance_threshold: float = 0.7,
                                limit: int = 10) -> list:
        cursor = self._get_cursor()
        if not cursor:
            from .json_store import JsonMemoryStore
            return JsonMemoryStore().get_important_memories(
                elder_id, importance_threshold, limit
            )
        try:
            cursor.execute("""
                SELECT content as event, sentiment, importance,
                       memory_type, topic_tags, date
                FROM elder_memories
                WHERE elder_id = %s AND importance >= %s
                ORDER BY importance DESC, date DESC
                LIMIT %s
            """, (elder_id, importance_threshold, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"撈取重要記憶失敗：{e}")
            return []

    def get_recent_conversation_summary(self, elder_id: str,
                                         limit: int = 6) -> list:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore().get_recent_conversation_summary(
            elder_id, limit
        )

    def search_similar_memories(self, elder_id: str,
                                  query_embedding: list,
                                  limit: int = 5) -> list:
        cursor = self._get_cursor()
        if not cursor:
            return []
        try:
            embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
            cursor.execute("""
                SELECT content as event, sentiment, importance,
                       memory_type, topic_tags, date,
                       embedding <=> %s::vector AS distance
                FROM elder_memories
                WHERE elder_id = %s
                  AND embedding IS NOT NULL
                ORDER BY distance ASC
                LIMIT %s
            """, (embedding_str, elder_id, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"向量搜尋失敗：{e}")
            return []

    def update_embedding(self, memory_id: int, embedding: list) -> bool:
        cursor = self._get_cursor()
        if not cursor:
            return False
        try:
            embedding_str = "[" + ",".join(map(str, embedding)) + "]"
            cursor.execute("""
                UPDATE elder_memories
                SET embedding = %s::vector
                WHERE id = %s
            """, (embedding_str, memory_id))
            return True
        except Exception as e:
            print(f"更新向量失敗：{e}")
            return False

    def update_profile(self, elder_id: str, data: dict) -> bool:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore().update_profile(elder_id, data)

    def _save(self, elder_id: str, data: dict) -> bool:
        from .json_store import JsonMemoryStore
        return JsonMemoryStore()._save(elder_id, data)