import os
from datetime import datetime
from backend.services.llm_service import LLMService
from backend.memory.vector_store import VectorMemoryStore
from backend.services.embedding_service import EmbeddingService


class MagicAI:
    """Manage one session's conversational context.

    ``conversation_history`` is the short-term context owned by this agent
    instance. Its file is best-effort crash recovery, not long-term memory.
    Structured ``recent_events`` and memory summaries are the persisted context
    shared across sessions.
    """

    def __init__(self, elder_id: str, persona_id: str = None):
        self.elder_id = elder_id
        self.persona_id = persona_id
        self._persona_key = persona_id or "ai"
        self.llm = LLMService(os.getenv("MAGIC_MODEL", "gemini-2.5-pro"))
        self.memory = VectorMemoryStore()
        self.embedding = EmbeddingService()
        self.profile = self.memory.get_profile(elder_id)
        self._chat_count = 0
        # Restore conversation history from disk so context survives server restarts.
        self.conversation_history: list[dict] = self.memory.load_conversation(
            elder_id, self._persona_key
        )
        print(
            f"{elder_id} 開始新的對話 session"
            f"（載入 {len(self.conversation_history)} 條歷史記錄，persona={self._persona_key}）"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_honorific(self) -> str:
        return "爺爺" if self.profile.get("gender", "male") == "male" else "奶奶"

    def _get_active_persona(self) -> dict:
        personas = self.profile.get("personas", {})
        active_id = self.persona_id or self.profile.get("active_persona", "ai")
        return personas.get(active_id, personas.get("ai", {}))

    def _reset_biography_usage(self):
        if not self.memory.update_profile(
            self.elder_id,
            {"biography_usage_count": 0},
        ):
            print("生平使用次數重設失敗")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def greet(self) -> str:
        hour = datetime.now().hour
        if hour < 12:
            time_greeting = "早安"
        elif hour < 18:
            time_greeting = "午安"
        else:
            time_greeting = "晚安"

        name = self.profile.get("name", "長者")
        active_persona = self._get_active_persona()
        honorific = active_persona.get("honorific", self._get_honorific())
        greeting = f"{name}{honorific}，{time_greeting}！今天感覺怎麼樣呀？"

        now = datetime.now()
        self.conversation_history.append({
            "role": "model",
            "content": greeting,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
        })
        return greeting

    def chat(self, user_message: str, use_rag: bool = True) -> str:
        active_id = self.persona_id or self.profile.get("active_persona", "ai")
        active_persona = self._get_active_persona()

        recent_messages = self.conversation_history[-4:]

        similar_memories = []
        if use_rag:
            try:
                query_embedding = self.embedding.embed(user_message)
                if query_embedding:
                    similar_memories = self.memory.search_similar_memories(
                        self.elder_id,
                        query_embedding,
                        limit=5,
                        persona_id=active_id,
                        query_text=user_message,
                    )
                    if similar_memories:
                        print(f"找到 {len(similar_memories)} 筆相關記憶")
                else:
                    similar_memories = self.memory.search_similar_memories(
                        self.elder_id,
                        [],
                        limit=5,
                        persona_id=active_id,
                        query_text=user_message,
                    )
            except Exception as e:
                print(f"向量搜尋失敗（不影響對話）：{e}")

        _SAFETY_TAGS = {"安全警報", "趨勢警報"}
        important_memories = [
            m for m in self.memory.get_important_memories(
                self.elder_id, importance_threshold=0.7, limit=12, persona_id=active_id
            )
            if not _SAFETY_TAGS.intersection(m.get("topic_tags") or [])
        ][:8]

        response = self.llm.chat(
            profile=self.profile,
            conversation_history=self.conversation_history,
            user_message=user_message,
            recent_messages=recent_messages,
            important_memories=important_memories,
            similar_memories=similar_memories,
            active_persona=active_persona,
        )

        self._record_response(user_message, response, len(similar_memories))

        return response

    def stream_chat(self, user_message: str, use_rag: bool = True):
        active_id = self.persona_id or self.profile.get("active_persona", "ai")
        active_persona = self._get_active_persona()
        recent_messages = self.conversation_history[-4:]

        similar_memories = []
        if use_rag:
            try:
                query_embedding = self.embedding.embed(user_message)
                similar_memories = self.memory.search_similar_memories(
                    self.elder_id,
                    query_embedding or [],
                    limit=5,
                    persona_id=active_id,
                    query_text=user_message,
                )
            except Exception as e:
                print(f"向量搜尋失敗（不影響對話）：{e}")

        _SAFETY_TAGS = {"安全警報", "趨勢警報"}
        important_memories = [
            m for m in self.memory.get_important_memories(
                self.elder_id, importance_threshold=0.7, limit=12, persona_id=active_id
            )
            if not _SAFETY_TAGS.intersection(m.get("topic_tags") or [])
        ][:8]

        chunks = []
        for chunk in self.llm.stream_chat(
            profile=self.profile,
            conversation_history=self.conversation_history,
            user_message=user_message,
            recent_messages=recent_messages,
            important_memories=important_memories,
            similar_memories=similar_memories,
            active_persona=active_persona,
        ):
            if chunk:
                chunks.append(chunk)
                yield chunk

        response = "".join(chunks)
        if response:
            self._record_response(
                user_message,
                response,
                len(similar_memories),
            )

    def _record_response(
        self,
        user_message: str,
        response: str,
        rag_hits: int,
    ):
        now = datetime.now()
        ts = {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S")}
        self.conversation_history.append({"role": "user", "content": user_message, **ts})
        self.conversation_history.append({
            "role": "model",
            "content": response,
            "_rag_hits": rag_hits,
            **ts,
        })

        if len(self.conversation_history) > 50:
            self.conversation_history = self.conversation_history[-50:]

        self._chat_count += 1

        if self._chat_count % 5 == 0:
            self._reset_biography_usage()
            try:
                self.memory.save_conversation(
                    self.elder_id,
                    self.conversation_history,
                    self._persona_key,
                )
            except Exception as e:
                print(f"對話歷史儲存失敗（不影響對話）：{e}")

        if self._chat_count % 10 == 0:
            self._summarize_memories()

    def _summarize_memories(self):
        try:
            events = self.memory.get_recent_events(self.elder_id, limit=10)
            if len(events) < 5:
                return

            name = self.profile.get("name", "長者")
            summary = self.llm.generate_memory_summary(events, name)
            print(f"記憶彙整完成：{summary[:50]}...")

            updated = self.memory.update_profile(
                self.elder_id,
                {
                    "memory_summary": {
                    "content": summary,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "based_on_events": len(events),
                    }
                },
            )
            if not updated:
                print("記憶彙整儲存失敗")

        except Exception as e:
            print(f"記憶彙整失敗（不影響對話）：{e}")

    def clear_memory(self):
        self.conversation_history = []
        try:
            if not self.memory.clear_conversation(
                self.elder_id,
                self._persona_key,
            ):
                print("對話歷史檔案清除失敗")
        except Exception as e:
            print(f"對話歷史檔案清除失敗：{e}")

    def flush_conversation(self) -> bool:
        return self.memory.save_conversation(
            self.elder_id,
            self.conversation_history,
            self._persona_key,
        )

    def get_history(self) -> list:
        return self.conversation_history
