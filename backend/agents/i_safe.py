from backend.memory.vector_store import VectorMemoryStore
from backend.services.embedding_service import EmbeddingService
from datetime import datetime


class ISafe:

    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.memory = VectorMemoryStore()
        self.embedding = EmbeddingService()
        from backend.services.llm_service import LLMService
        self.llm = LLMService()
        self.emotion_history = []
        self.alert_triggered = False

    def analyze(self, message: str, speed_emotion: str = "normal") -> dict:
        spoken_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        result = self.llm.analyze_emotion(message)
        print(f"情緒分析結果：emotion={result.get('emotion')}, importance={result.get('importance')}")

        if speed_emotion == "slow" and result.get("emotion") == "normal":
            result["emotion"] = "comfort"
            result["reason"] = (result.get("reason", "") + "（語速偵測：說話緩慢）").strip()
            print("語速修正：說話緩慢 → comfort")

        if speed_emotion == "fast" and result.get("emotion") == "normal":
            result["emotion"] = "urgent"
            result["reason"] = (result.get("reason", "") + "（語速偵測：說話急促）").strip()
            print("語速修正：說話急促 → urgent")

        # 分級響應判斷
        escalation_level = self._determine_escalation(message, result)
        result["escalation_level"] = escalation_level
        if escalation_level >= 2:
            print(f"⚠️ 分級響應：level={escalation_level}，需要通知照護人員")

        trend_alert = self._analyze_trend(result["emotion"])
        if trend_alert:
            result["trend_alert"] = trend_alert
            print(f"情緒趨勢警報：{trend_alert}")

        if result.get("should_record"):
            self._record_event(     
                message=message,
                sentiment=result["sentiment"],
                is_urgent=result["is_urgent"],
                reason=result.get("reason", ""),
                importance=result.get("importance", 0.5),
                memory_type=result.get("memory_type", "short"),
                emotion_score=result.get("emotion_score", 0.0),
                spoken_at=spoken_at,
                escalation_level=escalation_level
            )

        return result

    def _determine_escalation(self, message: str, emotion_result: dict) -> int:
        """
        分級響應判斷
        0: normal - AI 自行處理
        1: concern - AI 安撫 + 後台警示
        2: urgent - AI 安撫 + 通知照護人員
        3: emergency - 最高緊急，立刻通知
        """
        emotion = emotion_result.get("emotion", "normal")
        importance = emotion_result.get("importance", 0)
        is_urgent = emotion_result.get("is_urgent", False)

        # Level 3: 最高緊急
        emergency_keywords = [
            "跌倒", "跌落", "昏倒", "失去意識", "不能動",
            "胸口很痛", "胸痛", "心臟", "喘不過氣", "呼吸困難",
            "出血", "流血", "骨折", "救命", "快叫救護車"
        ]
        if any(kw in message for kw in emergency_keywords):
            return 3

        # Level 2: 需要通知照護人員
        if is_urgent and importance >= 0.7:
            return 2

        urgent_keywords = [
            "頭很暈", "快跌倒", "站不穩", "看不清楚",
            "很痛", "痛到", "劇烈", "好暈", "想吐"
        ]
        if any(kw in message for kw in urgent_keywords):
            return 2

        # Level 1: AI 安撫但後台標記
        if emotion in ["urgent", "comfort"] or is_urgent:
            return 1

        # Level 0: 正常
        return 0

    def _analyze_trend(self, current_emotion: str) -> str | None:
        self.emotion_history.append(current_emotion)
        if len(self.emotion_history) > 5:
            self.emotion_history = self.emotion_history[-5:]

        recent = self.emotion_history[-3:]

        if len(recent) == 3 and all(e == "urgent" for e in recent):
            if not self.alert_triggered:
                self.alert_triggered = True
                self._record_trend_event(
                    "連續三次偵測到緊急狀況，請立即確認長者狀態！", "urgent"
                )
                return "🚨 緊急趨勢警報：連續三次偵測到緊急狀況！"

        elif len(recent) == 3 and all(e in ["comfort", "urgent"] for e in recent):
            if not self.alert_triggered:
                self.alert_triggered = True
                self._record_trend_event(
                    "長者持續情緒低落，建議照護人員關心。", "negative"
                )
                return "⚠️ 情緒趨勢警報：長者持續情緒低落"

        elif current_emotion in ["happy", "normal"]:
            self.alert_triggered = False

        return None

    def _record_trend_event(self, message: str, trend_type: str):
        self.memory.add_event(
            elder_id=self.elder_id,
            event={
                "event": f"趨勢警報：{message}",
                "sentiment": "negative",
                "emotion_score": -1.0 if trend_type == "urgent" else -0.8,
                "importance": 1.0,
                "memory_type": "long",
                "topic_tags": ["趨勢警報", "需要關注"],
                "reason": message,
                "source": "trend_analysis",
                "spoken_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        )

    def _record_event(self, message: str, sentiment: str,
                        is_urgent: bool, reason: str = "",
                        importance: float = 0.5, memory_type: str = "short",
                        emotion_score: float = 0.0,
                        spoken_at: str = None, escalation_level: int = 0):
        topic_tags = ["安全警報"] if is_urgent else ["情緒"]

        event = {
            "event": f"說了：{message[:50]}",
            "sentiment": sentiment,
            "emotion_score": emotion_score,
            "importance": importance,
            "memory_type": memory_type,
            "topic_tags": topic_tags,
            "reason": reason,
            "source": "voice",
            "spoken_at": spoken_at
        }

        self.memory.add_event(elder_id=self.elder_id, event=event)

        try:
            embedding = self.embedding.embed(message)
            if embedding:
                cursor = self.memory._get_cursor()
                if cursor:
                    cursor.execute("""
                        SELECT id FROM elder_memories
                        WHERE elder_id = %s
                        ORDER BY created_at DESC LIMIT 1
                    """, (self.elder_id,))
                    row = cursor.fetchone()
                    if row:
                        self.memory.update_embedding(row['id'], embedding)
                        print(f"向量已儲存，維度：{len(embedding)}")
        except Exception as e:
            print(f"向量生成失敗（不影響對話）：{e}")

    def get_safety_status(self) -> dict:
        events = self.memory.get_recent_events(self.elder_id, limit=10)
        urgent_count = sum(1 for e in events if "安全警報" in e.get("topic_tags", []))
        negative_count = sum(1 for e in events if e.get("sentiment") == "negative")
        trend_alerts = sum(1 for e in events if "趨勢警報" in e.get("topic_tags", []))

        return {
            "elder_id": self.elder_id,
            "urgent_count": urgent_count,
            "negative_count": negative_count,
            "trend_alerts": trend_alerts,
            "hazard_level": "high" if urgent_count > 0 or trend_alerts > 0 else "low",
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
