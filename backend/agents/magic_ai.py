import os
from dotenv import load_dotenv
from backend.services.llm_service import LLMService
from backend.memory.vector_store import VectorMemoryStore
from backend.services.embedding_service import EmbeddingService
from datetime import datetime

load_dotenv()

class MagicAI:

    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.llm = LLMService()
        self.memory = VectorMemoryStore()
        self.embedding = EmbeddingService()
        self.profile = self.memory.get_profile(elder_id)
        self.conversation_history = []  # 不再從檔案載入
        self._chat_count = 0
        print(f"{elder_id} 開始新的對話 session")

    def _get_honorific(self) -> str:
        gender = self.profile.get("gender", "male")
        return "爺爺" if gender == "male" else "奶奶"

    def greet(self) -> str:
        hour = datetime.now().hour
        if hour < 12:
            time_greeting = "早安"
        elif hour < 18:
            time_greeting = "午安"
        else:
            time_greeting = "晚安"

        name = self.profile.get("name", "長者")
        personas = self.profile.get("personas", {})
        active_id = self.profile.get("active_persona", "ai")
        active_persona = personas.get(active_id, personas.get("ai", {}))
        honorific = active_persona.get("honorific", self._get_honorific())
        greeting = f"{name}{honorific}，{time_greeting}！今天感覺怎麼樣呀？"

        self.conversation_history.append({
            "role": "model",
            "content": greeting
        })
        return greeting

    def chat(self, user_message: str) -> str:
        recent_messages = self.memory.get_recent_conversation_summary(
            self.elder_id, limit=6
        )

        similar_memories = []
        try:
            query_embedding = self.embedding.embed(user_message)
            if query_embedding:
                similar_memories = self.memory.search_similar_memories(
                    self.elder_id, query_embedding, limit=5
                )
                if similar_memories:
                    print(f"找到 {len(similar_memories)} 筆相關記憶")
        except Exception as e:
            print(f"向量搜尋失敗（不影響對話）：{e}")

        important_memories = self.memory.get_important_memories(
            self.elder_id, importance_threshold=0.7, limit=8
        )

        personas = self.profile.get("personas", {})
        active_id = self.profile.get("active_persona", "ai")
        active_persona = personas.get(active_id, personas.get("ai", {}))

        response = self.llm.chat(
            profile=self.profile,
            conversation_history=self.conversation_history,
            user_message=user_message,
            recent_messages=recent_messages,
            important_memories=important_memories,
            similar_memories=similar_memories,
            active_persona=active_persona
        )

        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "model", "content": response})

        if len(self.conversation_history) > 50:
            self.conversation_history = self.conversation_history[-50:]

        self._chat_count += 1

        # 每 5 次重置生平使用計數
        if self._chat_count % 5 == 0:
            profile = self.memory.get_profile(self.elder_id)
            if profile:
                profile["biography_usage_count"] = 0
                self.memory._save(self.elder_id, profile)

        if self._chat_count % 10 == 0:
            self._summarize_memories()

        return response

    def _summarize_memories(self):
        try:
            events = self.memory.get_recent_events(self.elder_id, limit=10)
            if len(events) < 5:
                return

            name = self.profile.get("name", "長者")
            honorific = self._get_honorific()

            events_text = "\n".join([
                f"- {e.get('date', '')}：{e.get('event', '')}（情緒：{e.get('sentiment', '')}）"
                for e in events
            ])

            prompt = f"""請把以下關於{name}{honorific}的對話紀錄，彙整成一段簡短的摘要（100字以內）：

{events_text}

要求：
- 用第三人稱描述
- 重點放在長者的情緒狀態和重要事件
- 不要列點，用自然語句
- 只回傳摘要文字，不要其他說明"""

            from google import genai
            from google.genai import types
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=500,
                )
            )

            summary = response.text.strip()
            print(f"記憶彙整完成：{summary[:50]}...")

            profile = self.memory.get_profile(self.elder_id)
            if profile:
                profile["memory_summary"] = {
                    "content": summary,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "based_on_events": len(events)
                }
                self.memory._save(self.elder_id, profile)

        except Exception as e:
            print(f"記憶彙整失敗（不影響對話）：{e}")

    def clear_memory(self):
        self.conversation_history = []
        self.memory.clear_conversation(self.elder_id)

    def get_history(self) -> list:
        return self.conversation_history