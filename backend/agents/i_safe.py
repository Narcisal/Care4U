from backend.memory.json_store import JsonMemoryStore
from datetime import datetime

class ISafe:
    """安全感知 Agent，分析長者訊息中的安全風險"""

    # 各等級關鍵字
    URGENT_KEYWORDS = ["跌倒", "頭暈", "胸痛", "喘不過氣", "昏倒", "救命", "好痛", "站不起來"]
    NEGATIVE_KEYWORDS = ["痛", "不舒服", "難過", "孤單", "無聊", "累", "不高興", "煩", "憂鬱", "想哭"]
    POSITIVE_KEYWORDS = ["開心", "高興", "快樂", "好棒", "謝謝", "喜歡", "高興", "很好"]

    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.memory = JsonMemoryStore()

    def analyze(self, message: str) -> dict:
        """
        分析訊息，回傳安全狀態與情緒標籤
        回傳格式：
        {
            "emotion": "urgent" | "comfort" | "happy" | "normal",
            "is_urgent": bool,
            "sentiment": "negative" | "positive" | "neutral",
            "should_record": bool
        }
        """
        is_urgent = any(kw in message for kw in self.URGENT_KEYWORDS)
        is_negative = any(kw in message for kw in self.NEGATIVE_KEYWORDS)
        is_positive = any(kw in message for kw in self.POSITIVE_KEYWORDS)

        if is_urgent:
            emotion = "urgent"
            sentiment = "negative"
            should_record = True
        elif is_negative:
            emotion = "comfort"
            sentiment = "negative"
            should_record = True
        elif is_positive:
            emotion = "happy"
            sentiment = "positive"
            should_record = False
        else:
            emotion = "normal"
            sentiment = "neutral"
            should_record = False

        result = {
            "emotion": emotion,
            "is_urgent": is_urgent,
            "sentiment": sentiment,
            "should_record": should_record
        }

        # 如果需要記錄，寫入記憶
        if should_record:
            self._record_event(message, sentiment, is_urgent)

        return result

    def _record_event(self, message: str, sentiment: str, is_urgent: bool):
        """寫入情緒或安全事件到記憶"""
        topic_tags = ["安全警報"] if is_urgent else ["情緒"]
        self.memory.add_event(
            elder_id=self.elder_id,
            event={
                "event": f"說了：{message[:50]}",
                "sentiment": sentiment,
                "emotion_score": -0.9 if is_urgent else -0.7,
                "topic_tags": topic_tags,
                "source": "voice"
            }
        )

    def get_safety_status(self) -> dict:
        """取得近期安全狀態摘要（預留給後台顯示）"""
        events = self.memory.get_recent_events(self.elder_id, limit=10)
        urgent_count = sum(1 for e in events if "安全警報" in e.get("topic_tags", []))
        negative_count = sum(1 for e in events if e.get("sentiment") == "negative")

        return {
            "elder_id": self.elder_id,
            "urgent_count": urgent_count,
            "negative_count": negative_count,
            "hazard_level": "high" if urgent_count > 0 else "low",
            "last_checked": str(datetime.now().strftime("%Y-%m-%d %H:%M"))
        }