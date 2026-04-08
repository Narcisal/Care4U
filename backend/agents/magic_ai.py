from backend.services.llm_service import LLMService
from backend.memory.json_store import JsonMemoryStore
from datetime import datetime

class MagicAI:
    
    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.llm = LLMService()
        self.memory = JsonMemoryStore()
        self.conversation_history = []
        self.profile = self.memory.get_profile(elder_id)
        
    def greet(self) -> str:
        """系統啟動時主動問候"""
        hour = datetime.now().hour
        if hour < 12:
            time_greeting = "早安"
        elif hour < 18:
            time_greeting = "午安"
        else:
            time_greeting = "晚安"
        
        name = self.profile.get("name", "爺爺/奶奶")
        greeting = f"{name}，{time_greeting}！今天感覺怎麼樣呀？"
        
        # 把問候加入對話歷史
        self.conversation_history.append({
            "role": "model",
            "content": greeting
        })
        
        return greeting
    
    def chat(self, user_message: str) -> str:
        """處理使用者訊息並回應"""
        
        # 偵測負面情緒關鍵字
        negative_keywords = ["痛", "不舒服", "難過", "孤單", "無聊", 
                            "累", "不高興", "煩", "憂鬱", "想哭"]
        is_negative = any(kw in user_message for kw in negative_keywords)
        
        # 取得 LLM 回應
        response = self.llm.chat(
            profile=self.profile,
            conversation_history=self.conversation_history,
            user_message=user_message
        )
        
        # 更新對話歷史
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        self.conversation_history.append({
            "role": "model", 
            "content": response
        })
        
        # 只保留最近 20 則對話，避免 token 過多
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
        
        # 如果偵測到負面情緒，記錄到記憶
        if is_negative:
            self.memory.add_event(
                elder_id=self.elder_id,
                event={
                    "event": f"說了：{user_message[:50]}",
                    "sentiment": "negative",
                    "emotion_score": -0.7,
                    "topic_tags": ["情緒"],
                    "source": "voice"
                }
            )
        
        return response
    
    def get_history(self) -> list:
        """取得對話歷史"""
        return self.conversation_history