from backend.services.llm_service import LLMService
from backend.memory.json_store import JsonMemoryStore
from datetime import datetime

class MagicAI:
    """第一線情感陪伴 Agent，專注對話品質"""

    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.llm = LLMService()
        self.memory = JsonMemoryStore()
        self.conversation_history = []
        self.profile = self.memory.get_profile(elder_id)

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
        honorific = self._get_honorific()
        greeting = f"{name}{honorific}，{time_greeting}！今天感覺怎麼樣呀？"

        self.conversation_history.append({
            "role": "model",
            "content": greeting
        })
        return greeting

    def chat(self, user_message: str) -> str:
        """純粹負責生成回應，不做情緒判斷"""
        response = self.llm.chat(
            profile=self.profile,
            conversation_history=self.conversation_history,
            user_message=user_message
        )

        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "model", "content": response})

        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

        return response

    def get_history(self) -> list:
        return self.conversation_history