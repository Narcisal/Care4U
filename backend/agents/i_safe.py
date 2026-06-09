import os
import re
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
# Escalation keyword tables
# ------------------------------------------------------------------

_EMERGENCY_ZH = [
    "跌倒", "跌落", "昏倒", "失去意識", "不能動",
    "胸口很痛", "胸痛", "心臟", "喘不過氣", "呼吸困難",
    "出血", "流血", "骨折", "救命", "快叫救護車",
    "站不住",
]
_EMERGENCY_EN = [
    "help", "fallen", "fall", "faint", "unconscious",
    "chest pain", "can't breathe", "bleeding", "broken bone", "call ambulance",
]

_URGENT_ZH = [
    "頭很暈", "快跌倒", "站不穩", "看不清楚",
    "很痛", "痛到", "劇烈", "好暈", "想吐",
]
_URGENT_EN = [
    "dizzy", "can't stand", "blurry", "nausea", "severe pain", "hurts a lot",
]

_SAFE_ZH = [
    "早安", "午安", "晚安", "謝謝", "天氣", "聊天", "故事",
    "回憶", "喜歡", "開心", "休息", "吃飯", "散步",
]
_SAFE_EN = [
    "good morning", "good afternoon", "good night", "thank you",
    "weather", "chat", "story", "memory", "happy", "rest", "meal", "walk",
]

# Physical symptom keywords: LLM 判 L1 但含這些詞時自動升 L2。
# 原則：能重判不能輕判，照護系統寧可多通知。
_PHYSICAL_SYMPTOM_L2 = [
    "腫", "痠痛", "使不上力", "沒有力", "腿軟", "腳軟", "膝軟",
    "記性", "記不住", "想不起", "忘了藥", "忘記藥", "沒吃藥",
    "胃口差", "胃口不好", "吃不下", "沒有食慾",
    "差點跌", "差點倒", "差點絆", "差點滑",
]

# Cooldown: suppress duplicate trend alerts within this window.
_TREND_ALERT_COOLDOWN_HOURS = 2


def _keyword_match(message: str, zh_keywords: list, en_keywords: list) -> bool:
    for kw in zh_keywords:
        if kw in message:
            return True
    msg_lower = message.lower()
    for kw in en_keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", msg_lower):
            return True
    return False


def quick_keyword_check(message: str) -> int | None:
    if _keyword_match(message, _EMERGENCY_ZH, _EMERGENCY_EN):
        return 3
    if _keyword_match(message, _URGENT_ZH, _URGENT_EN):
        return 2
    if _keyword_match(message, _SAFE_ZH, _SAFE_EN):
        return 0
    return None


class ISafe:

    def __init__(self, elder_id: str, persona_id: str = None):
        self.elder_id = elder_id
        self.persona_id = persona_id
        self.memory = VectorMemoryStore()
        self.embedding = EmbeddingService()
        self.llm = LLMService(os.getenv("ISAFE_MODEL", "gemini-2.0-flash"))
        self.emotion_history: list[str] = []
        profile = self.memory.get_profile(elder_id)
        self.active_persona_id = persona_id or (profile.get("active_persona", "ai") if profile else "ai")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, message: str, speed_emotion: str = "normal") -> dict:
        spoken_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        profile = self.memory.get_profile(self.elder_id)
        self.active_persona_id = self.persona_id or (profile.get("active_persona", "ai") if profile else "ai")

        keyword_level = quick_keyword_check(message)
        if keyword_level == 0:
            result = {
                "emotion": "normal",
                "emotion_score": 0.0,
                "importance": 0.3,
                "reason": "明確安全日常語句，使用快速路徑",
                "is_urgent": False,
                "sentiment": "neutral",
                "memory_type": "short",
                "should_record": False,
                "_llm_used": False,
                "_isafe_path": "safe_keyword",
            }
        else:
            result = self.llm.analyze_emotion(message)
            result["_llm_used"] = True
            result["_isafe_path"] = "llm"
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
        importance = float(result.get("importance", 0.3) or 0.3)
        tags = set(result.get("topic_tags", []) or [])

        if result.get("is_urgent") or _keyword_match(message, _EMERGENCY_ZH + _URGENT_ZH, _EMERGENCY_EN + _URGENT_EN):
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
        # 掃描所有事件（不限 10 筆），以「有無未確認警報」決定危險等級
        all_events = self.memory.get_recent_events(self.elder_id, limit=200)
        unacked = [e for e in all_events if e.get("acknowledged") is not True]
        urgent_unacked = [e for e in unacked if "安全警報" in e.get("topic_tags", [])]
        trend_unacked  = [e for e in unacked if "趨勢警報"  in e.get("topic_tags", [])]
        negative_count = sum(1 for e in all_events[-20:] if e.get("sentiment") == "negative")
        return {
            "elder_id": self.elder_id,
            "urgent_count": len(urgent_unacked),
            "trend_alerts": len(trend_unacked),
            "negative_count": negative_count,
            # high = 有任何未確認的安全/趨勢警報；全部確認後自動回正
            "hazard_level": "high" if (urgent_unacked or trend_unacked) else "low",
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # ------------------------------------------------------------------
    # Escalation logic
    # ------------------------------------------------------------------

    def _determine_escalation(self, message: str, emotion_result: dict) -> int:
        keyword_level = quick_keyword_check(message) or 0

        model_level = emotion_result.get("escalation_level")
        if isinstance(model_level, int) and 0 <= model_level <= 3:
            level = max(keyword_level, model_level)
        else:
            emotion = emotion_result.get("emotion", "normal")
            importance = emotion_result.get("importance", 0)
            is_urgent = emotion_result.get("is_urgent", False)
            if is_urgent and importance >= 0.7:
                llm_level = 2
            elif emotion in ["urgent", "comfort"] or is_urgent:
                llm_level = 1
            else:
                llm_level = 0
            level = max(keyword_level, llm_level)

        # Safety bump：任何身體症狀關鍵字出現時，L1 自動升 L2。
        # 原則：能重判不能輕判。
        if level == 1 and any(kw in message for kw in _PHYSICAL_SYMPTOM_L2):
            level = 2

        return level

    # ------------------------------------------------------------------
    # Trend analysis with persistent cooldown
    # ------------------------------------------------------------------

    def _check_trend_cooldown(self) -> bool:
        """Return True if a trend alert was already persisted within the cooldown window."""
        try:
            cutoff_ts = datetime.now().timestamp() - _TREND_ALERT_COOLDOWN_HOURS * 3600
            events = self.memory.get_recent_events(self.elder_id, limit=30)
            for e in reversed(events):
                if "趨勢警報" not in e.get("topic_tags", []):
                    continue
                raw = e.get("spoken_at") or f"{e.get('date', '')} {e.get('time', '')}"
                try:
                    ts = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").timestamp()
                    if ts >= cutoff_ts:
                        return True
                except (ValueError, TypeError):
                    continue
        except Exception:
            pass
        return False

    def _analyze_trend(self, current_emotion: str) -> str | None:
        self.emotion_history.append(current_emotion)
        if len(self.emotion_history) > 5:
            self.emotion_history = self.emotion_history[-5:]

        recent = self.emotion_history[-3:]

        if len(recent) == 3 and all(e == "urgent" for e in recent):
            if not self._check_trend_cooldown():
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
            if not self._check_trend_cooldown():
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

        return None

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _save_event(self, event: dict):
        memory_id = self.memory.add_event(elder_id=self.elder_id, event=event)
        if not isinstance(memory_id, int) or isinstance(memory_id, bool):
            return
        try:
            text = event.get("event", "")
            embedding = self.embedding.embed(text)
            if embedding:
                self.memory.save_event_embedding(memory_id, embedding)
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
