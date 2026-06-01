from datetime import datetime
from backend.memory.vector_store import VectorMemoryStore
from backend.services.embedding_service import EmbeddingService
from backend.services.llm_service import LLMService


def _log(text: str):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))

# ------------------------------------------------------------------
# Escalation keyword tables — extend here, not inside the method
# ------------------------------------------------------------------

_EMERGENCY_KEYWORDS = [
    "跌倒", "跌落", "昏倒", "失去意識", "不能動",
    "胸口很痛", "胸痛", "心臟", "喘不過氣", "呼吸困難",
    "出血", "流血", "骨折", "救命", "快叫救護車",
]

_URGENT_KEYWORDS = [
    "頭很暈", "快跌倒", "站不穩", "看不清楚",
    "很痛", "痛到", "劇烈", "好暈", "想吐",
]


class ISafe:

    def __init__(self, elder_id: str, persona_id: str = None):
        self.elder_id = elder_id
        self.persona_id = persona_id
        self.memory = VectorMemoryStore()
        self.embedding = EmbeddingService()
        self.llm = LLMService()
        self.emotion_history: list[str] = []
        self.alert_triggered = False
        profile = self.memory.get_profile(elder_id)
        self.active_persona_id = persona_id or (profile.get("active_persona", "ai") if profile else "ai")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, message: str, speed_emotion: str = "normal") -> dict:
        spoken_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        profile = self.memory.get_profile(self.elder_id)
        self.active_persona_id = self.persona_id or (profile.get("active_persona", "ai") if profile else "ai")

        result = self.llm.analyze_emotion(message)
        _log(f"情緒分析結果：emotion={result.get('emotion')}, importance={result.get('importance')}")
        result = self._apply_importance_rules(message, result)

        if speed_emotion == "slow" and result.get("emotion") == "normal":
            result["emotion"] = "comfort"
            result["reason"] = (result.get("reason", "") + "（語速偵測：說話緩慢）").strip()
            _log("語速修正：說話緩慢 -> comfort")

        elif speed_emotion == "fast" and result.get("emotion") == "normal":
            result["emotion"] = "urgent"
            result["reason"] = (result.get("reason", "") + "（語速偵測：說話急促）").strip()
            _log("語速修正：說話急促 -> urgent")

        escalation_level = self._determine_escalation(message, result)
        result["escalation_level"] = escalation_level
        if escalation_level >= 2:
            _log(f"分級響應：level={escalation_level}，需要通知照護人員")

        trend_alert = self._analyze_trend(result["emotion"])
        if trend_alert:
            result["trend_alert"] = trend_alert
            _log(f"情緒趨勢警報：{trend_alert}")

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
            )

        return result

    def _apply_importance_rules(self, message: str, result: dict) -> dict:
        """Stabilize memory importance beyond the raw LLM score."""
        importance = float(result.get("importance", 0.3) or 0.3)
        tags = set(result.get("topic_tags", []) or [])

        if result.get("is_urgent") or any(kw in message for kw in _EMERGENCY_KEYWORDS + _URGENT_KEYWORDS):
            importance = max(importance, 0.8)
            tags.add("安全警報")

        family_terms = ["爸爸", "媽媽", "女兒", "兒子", "孫", "阿公", "阿嬤", "太太", "先生", "老婆", "老伴"]
        memory_terms = ["以前", "年輕", "老家", "工作", "老師", "工程師", "裁縫", "結婚", "生日", "喜歡", "討厭"]
        if any(term in message for term in family_terms + memory_terms):
            importance = max(importance, 0.7)

        if result.get("emotion") in ["comfort", "urgent"]:
            importance = max(importance, 0.5)

        result["importance"] = min(round(importance, 2), 1.0)
        result["memory_type"] = "long" if result["importance"] >= 0.7 else "short"
        result["should_record"] = (
            result.get("should_record", False)
            or result["importance"] >= 0.5
            or result.get("emotion") in ["urgent", "comfort", "happy"]
        )
        if tags:
            result["topic_tags"] = list(tags)
        return result

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
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # ------------------------------------------------------------------
    # Escalation logic
    # ------------------------------------------------------------------

    def _determine_escalation(self, message: str, emotion_result: dict) -> int:
        """
        0: normal  — AI handles alone
        1: concern — AI soothes + backend flag
        2: urgent  — AI soothes + notify caregiver
        3: emergency — immediate caregiver notification
        """
        if any(kw in message for kw in _EMERGENCY_KEYWORDS):
            return 3

        emotion = emotion_result.get("emotion", "normal")
        importance = emotion_result.get("importance", 0)
        is_urgent = emotion_result.get("is_urgent", False)

        if is_urgent and importance >= 0.7:
            return 2

        if any(kw in message for kw in _URGENT_KEYWORDS):
            return 2

        if emotion in ["urgent", "comfort"] or is_urgent:
            return 1

        return 0

    # ------------------------------------------------------------------
    # Trend analysis
    # ------------------------------------------------------------------

    def _analyze_trend(self, current_emotion: str) -> str | None:
        self.emotion_history.append(current_emotion)
        if len(self.emotion_history) > 5:
            self.emotion_history = self.emotion_history[-5:]

        recent = self.emotion_history[-3:]

        if len(recent) == 3 and all(e == "urgent" for e in recent):
            if not self.alert_triggered:
                self.alert_triggered = True
                self._save_event({
                    "event": "趨勢警報：連續三次偵測到緊急狀況，請立即確認長者狀態！",
                    "sentiment": "negative",
                    "emotion_score": -1.0,
                    "importance": 1.0,
                    "memory_type": "long",
                    "persona_id": self.active_persona_id,
                    "topic_tags": ["趨勢警報", "需要關注"],
                    "reason": "連續三次偵測到緊急狀況，請立即確認長者狀態！",
                    "source": "trend_analysis",
                    "spoken_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                return "緊急趨勢警報：連續三次偵測到緊急狀況！"

        elif len(recent) == 3 and all(e in ["comfort", "urgent"] for e in recent):
            if not self.alert_triggered:
                self.alert_triggered = True
                self._save_event({
                    "event": "趨勢警報：長者持續情緒低落，建議照護人員關心。",
                    "sentiment": "negative",
                    "emotion_score": -0.8,
                    "importance": 1.0,
                    "memory_type": "long",
                    "persona_id": self.active_persona_id,
                    "topic_tags": ["趨勢警報", "需要關注"],
                    "reason": "長者持續情緒低落，建議照護人員關心。",
                    "source": "trend_analysis",
                    "spoken_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                return "情緒趨勢警報：長者持續情緒低落"

        elif current_emotion in ["happy", "normal"]:
            self.alert_triggered = False

        return None

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _save_event(self, event: dict):
        """Persist an event to memory and store its embedding if available."""
        self.memory.add_event(elder_id=self.elder_id, event=event)
        try:
            text = event.get("event", "")
            embedding = self.embedding.embed(text)
            if embedding:
                cursor = self.memory._get_cursor()
                if cursor:
                    cursor.execute(
                        """
                        SELECT id FROM elder_memories
                        WHERE elder_id = %s
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (self.elder_id,),
                    )
                    row = cursor.fetchone()
                    if row:
                        self.memory.update_embedding(row["id"], embedding)
                        _log(f"向量已儲存，維度：{len(embedding)}")
        except Exception as e:
            _log(f"向量生成失敗（不影響對話）：{e}")

    def _record_event(
        self,
        message: str,
        sentiment: str,
        is_urgent: bool,
        reason: str = "",
        importance: float = 0.5,
        memory_type: str = "short",
        emotion_score: float = 0.0,
        spoken_at: str = None,
    ):
        self._save_event({
            "event": f"說了：{message[:50]}",
            "sentiment": sentiment,
            "emotion_score": emotion_score,
            "importance": importance,
            "memory_type": memory_type,
            "persona_id": self.active_persona_id,
            "topic_tags": ["安全警報"] if is_urgent else ["情緒"],
            "reason": reason,
            "source": "voice",
            "spoken_at": spoken_at,
        })
