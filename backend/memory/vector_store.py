import os
import threading
from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

from .memory_manager import BiographyUpdateResult, MemoryManager
from .json_store import JsonMemoryStore

load_dotenv(override=True)

# Module-level connection pool — shared across all VectorMemoryStore instances.
_db_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_init_lock = threading.Lock()


def _build_conn_params() -> dict:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 5433)),
        "dbname": os.getenv("DB_NAME", "aicaeru"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "1")),
    }


def _init_pool() -> psycopg2.pool.ThreadedConnectionPool | None:
    global _db_pool
    if _db_pool is not None:
        return _db_pool
    with _pool_init_lock:
        if _db_pool is not None:
            return _db_pool
        try:
            max_conn = int(os.getenv("DB_POOL_MAX", "5"))
            _db_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=max_conn,
                **_build_conn_params(),
            )
            print(f"PostgreSQL 連線池初始化成功（最大 {max_conn} 連線）！")
        except Exception as e:
            print(f"PostgreSQL 連線池初始化失敗：{e}")
            _db_pool = None
    return _db_pool


def close_db_pool():
    global _db_pool
    if _db_pool is None:
        return
    try:
        _db_pool.closeall()
    finally:
        _db_pool = None


class VectorMemoryStore(MemoryManager):

    def __init__(self):
        self._json = JsonMemoryStore()
        self.db_enabled = os.getenv("DB_ENABLED", "false").lower() == "true"
        if self.db_enabled:
            _init_pool()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @contextmanager
    def _get_conn(self):
        """Borrow a connection from the pool; yield None if DB is disabled or unavailable."""
        pool = _db_pool
        if not self.db_enabled or pool is None:
            yield None
            return
        conn = None
        try:
            conn = pool.getconn()
            conn.autocommit = True
        except Exception as e:
            print(f"DB 連線借用失敗：{e}")
        try:
            yield conn
        finally:
            if conn is not None:
                try:
                    pool.putconn(conn)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _to_pgvector_str(embedding: list) -> str:
        return "[" + ",".join(map(str, embedding)) + "]"

    # ------------------------------------------------------------------
    # MemoryManager interface — delegates to JSON store
    # ------------------------------------------------------------------

    def get_profile(self, elder_id: str) -> dict:
        return self._json.get_profile(elder_id)

    def save_profile(self, elder_id: str, profile: dict) -> bool:
        return self._json.save_profile(elder_id, profile)

    def _save(self, elder_id: str, data: dict) -> bool:
        """Private alias kept for internal callers; prefer save_profile()."""
        return self._json._save(elder_id, data)

    def save_conversation(self, elder_id: str, history: list, persona_id: str = "ai") -> bool:
        return self._json.save_conversation(elder_id, history, persona_id)

    def load_conversation(self, elder_id: str, persona_id: str = "ai") -> list:
        return self._json.load_conversation(elder_id, persona_id)

    def clear_conversation(self, elder_id: str, persona_id: str = "ai") -> bool:
        return self._json.clear_conversation(elder_id, persona_id)

    def get_recent_conversation_summary(self, elder_id: str, limit: int = 6, persona_id: str = "ai") -> list:
        return self._json.get_recent_conversation_summary(elder_id, limit, persona_id)

    def update_profile(self, elder_id: str, data: dict) -> bool:
        return self._json.update_profile(elder_id, data)

    def append_family_note(self, elder_id: str, note_dict: dict) -> bool:
        return self._json.append_family_note(elder_id, note_dict)

    def delete_family_note_at(self, elder_id: str, index: int) -> bool:
        return self._json.delete_family_note_at(elder_id, index)

    def set_persona(self, elder_id: str, persona_id: str, persona_dict: dict) -> bool:
        return self._json.set_persona(elder_id, persona_id, persona_dict)

    def add_persona_auto(self, elder_id: str, persona_dict: dict) -> str | None:
        return self._json.add_persona_auto(elder_id, persona_dict)

    def delete_persona(self, elder_id: str, persona_id: str) -> bool:
        return self._json.delete_persona(elder_id, persona_id)

    def set_active_persona(self, elder_id: str, persona_id: str) -> bool:
        return self._json.set_active_persona(elder_id, persona_id)

    def set_persona_field(
        self,
        elder_id: str,
        persona_id: str,
        field: str,
        value,
    ) -> bool:
        return self._json.set_persona_field(elder_id, persona_id, field, value)

    def set_biography(
        self,
        elder_id: str,
        biography_dict: dict,
        *,
        skip_if_manual: bool = False,
        preserve_sources: bool = False,
    ) -> BiographyUpdateResult:
        return self._json.set_biography(
            elder_id,
            biography_dict,
            skip_if_manual=skip_if_manual,
            preserve_sources=preserve_sources,
        )

    def update_basic_fields(self, elder_id: str, fields_dict: dict) -> bool:
        return self._json.update_basic_fields(elder_id, fields_dict)

    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        return self._json.get_recent_events(elder_id, limit)

    def acknowledge_event_at(self, elder_id: str, index: int) -> bool:
        return self._json.acknowledge_event_at(elder_id, index)

    def acknowledge_events_by_tag(self, elder_id: str, tag: str) -> int:
        return self._json.acknowledge_events_by_tag(elder_id, tag)

    # ------------------------------------------------------------------
    # Dual-write: JSON + PostgreSQL
    # ------------------------------------------------------------------

    def add_event(self, elder_id: str, event: dict) -> int | bool:
        if not self._json.add_event(elder_id, event):
            return False

        with self._get_conn() as conn:
            if conn is None:
                return False
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO elder_memories
                            (elder_id, content, sentiment, importance, memory_type,
                             topic_tags, spoken_at, date, persona_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
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
                    row = cursor.fetchone()
                return row[0] if row else False
            except Exception as e:
                print(f"寫入 PostgreSQL 失敗：{e}")
                return False

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def save_event_embedding(self, memory_id: int, embedding: list) -> bool:
        with self._get_conn() as conn:
            if conn is None:
                return False
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE elder_memories SET embedding = %s::vector WHERE id = %s",
                        (self._to_pgvector_str(embedding), memory_id),
                    )
                    print(f"向量已儲存，維度：{len(embedding)}")
                return True
            except Exception as e:
                print(f"向量儲存失敗：{e}")
                return False

    def update_embedding(self, memory_id: int, embedding: list) -> bool:
        with self._get_conn() as conn:
            if conn is None:
                return False
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE elder_memories SET embedding = %s::vector WHERE id = %s",
                        (self._to_pgvector_str(embedding), memory_id),
                    )
                return True
            except Exception as e:
                print(f"更新向量失敗：{e}")
                return False

    # ------------------------------------------------------------------
    # Vector / importance queries (PostgreSQL with JSON fallback)
    # ------------------------------------------------------------------

    def get_important_memories(
        self,
        elder_id: str,
        importance_threshold: float = 0.7,
        limit: int = 10,
        persona_id: str = None,
    ) -> list:
        with self._get_conn() as conn:
            if conn is None:
                return self._json.get_important_memories(elder_id, importance_threshold, limit)
            try:
                params: list = [elder_id, importance_threshold]
                persona_clause = ""
                if persona_id and persona_id != "ai":
                    persona_clause = "AND (persona_id = %s OR persona_id IS NULL OR persona_id = 'ai')"
                    params.append(persona_id)
                params.append(limit)
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
                return self._json.get_important_memories(
                    elder_id,
                    importance_threshold,
                    limit,
                )

    def search_similar_memories(
        self,
        elder_id: str,
        query_embedding: list,
        limit: int = 5,
        persona_id: str = None,
        query_text: str = "",
    ) -> list:
        with self._get_conn() as conn:
            if conn is None:
                return self._json.search_similar_memories(
                    elder_id, query_text, limit=limit, persona_id=persona_id
                )
            if not query_embedding:
                return self._json.search_similar_memories(
                    elder_id, query_text, limit=limit, persona_id=persona_id
                )
            try:
                emb_str = self._to_pgvector_str(query_embedding)
                params: list = [emb_str, elder_id]
                persona_clause = ""
                if persona_id and persona_id != "ai":
                    persona_clause = "AND (persona_id = %s OR persona_id IS NULL OR persona_id = 'ai')"
                    params.append(persona_id)
                params.append(limit)
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
                    rows = [dict(row) for row in cursor.fetchall()]
                # If PostgreSQL returned nothing (e.g. embeddings not yet stored),
                # fall back to JSON keyword search so RAG still works.
                if not rows and query_text:
                    return self._json.search_similar_memories(
                        elder_id, query_text, limit=limit, persona_id=persona_id
                    )
                return rows
            except Exception as e:
                print(f"向量搜尋失敗：{e}")
                return self._json.search_similar_memories(
                    elder_id,
                    query_text,
                    limit=limit,
                    persona_id=persona_id,
                )
