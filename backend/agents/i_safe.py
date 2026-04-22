from backend.memory.json_store import JsonMemoryStore
from datetime import datetime

class ISafe:
    """安全感知 Agent，使用 LLM 分析長者訊息的情緒與安全風險"""

    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.memory = JsonMemoryStore()
        # 延遲 import 避免循環依賴
        from backend.services.llm_service import LLMService
        self.llm = LLMService()

    def analyze(self, message: str) -> dict:
        """
        用 LLM 分析訊息，回傳安全狀態與情緒標籤
        如果 LLM 失敗，自動降級為關鍵字判斷
        """
        result = self.llm.analyze_emotion(message)

        # 如果需要記錄，寫入記憶
        if result.get("should_record"):
            self._record_event(
                message=message,
                sentiment=result["sentiment"],
                is_urgent=result["is_urgent"],
                reason=result.get("reason", "")
            )

        return result

    def _record_event(self, message: str, sentiment: str,
                      is_urgent: bool, reason: str = ""):
        """寫入情緒或安全事件到記憶"""
        topic_tags = ["安全警報"] if is_urgent else ["情緒"]
        self.memory.add_event(
            elder_id=self.elder_id,
            event={
                "event": f"說了：{message[:50]}",
                "sentiment": sentiment,
                "emotion_score": -0.9 if is_urgent else -0.7,
                "topic_tags": topic_tags,
                "reason": reason,
                "source": "voice"
            }
        )

    def get_safety_status(self) -> dict:
        """取得近期安全狀態摘要"""
        events = self.memory.get_recent_events(self.elder_id, limit=10)
        urgent_count = sum(1 for e in events if "安全警報" in e.get("topic_tags", []))
        negative_count = sum(1 for e in events if e.get("sentiment") == "negative")

        return {
            "elder_id": self.elder_id,
            "urgent_count": urgent_count,
            "negative_count": negative_count,
            "hazard_level": "high" if urgent_count > 0 else "low",
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M")
        }