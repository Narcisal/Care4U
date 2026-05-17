from datetime import datetime
import collections
from backend.agents.magic_ai import MagicAI
from backend.agents.i_safe import ISafe

_agent_logs = collections.deque(maxlen=100)

def _log(agent: str, action: str, detail: str):
    _agent_logs.appendleft({
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "action": action,
        "detail": detail
    })

def get_logs() -> list:
    return list(_agent_logs)

_magic_agents: dict[str, MagicAI] = {}
_isafe_agents: dict[str, ISafe] = {}

def _get_magic(elder_id: str) -> MagicAI:
    if elder_id not in _magic_agents:
        _magic_agents[elder_id] = MagicAI(elder_id)
    return _magic_agents[elder_id]

def _get_isafe(elder_id: str) -> ISafe:
    if elder_id not in _isafe_agents:
        _isafe_agents[elder_id] = ISafe(elder_id)
    return _isafe_agents[elder_id]

def clear_agent(elder_id: str):
    _magic_agents.pop(elder_id, None)
    _isafe_agents.pop(elder_id, None)


class Decision:

    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.magic = _get_magic(elder_id)
        self.isafe = _get_isafe(elder_id)
        self._setup_persona()

    def _setup_persona(self):
        """根據 active_persona 設定 TTS 引擎"""
        try:
            from backend.memory.vector_store import VectorMemoryStore
            from backend.services.tts_service import TTSService
            memory = VectorMemoryStore()
            profile = memory.get_profile(self.elder_id)
            personas = profile.get("personas", {})
            active_id = profile.get("active_persona", "ai")
            active = personas.get(active_id, personas.get("ai", {}))

            self.tts = TTSService()
            engine = active.get("voice_engine", "edge")
            voice_path = active.get("voice_path")

            if engine == "breezyvoice" and voice_path:
                self.tts.set_engine("breezyvoice", voice_path)
                print(f"TTS 切換為 BreezyVoice，聲音樣本：{voice_path}")
            else:
                self.tts.reset_engine()

            self.active_persona = active
            print(f"人格設定：{active.get('name', 'AI 助理')}")
        except Exception as e:
            print(f"人格設定失敗：{e}")
            from backend.services.tts_service import TTSService
            self.tts = TTSService()
            self.active_persona = {"name": "AI 助理", "honorific": "爺爺"}

    def greet(self) -> dict:
        try:
            greeting = self.magic.greet()
            return {
                "message": greeting,
                "emotion": "normal",
                "elder_id": self.elder_id,
                "persona_name": self.active_persona.get("name", "AI 助理")
            }
        except Exception as e:
            _log("MagicAI", "錯誤", f"問候失敗：{str(e)[:50]}")
            return {
                "message": "你好！今天感覺怎麼樣呀？",
                "emotion": "normal",
                "elder_id": self.elder_id,
                "persona_name": "AI 助理"
            }

    def chat(self, user_message: str,
            speed_emotion: str = "normal") -> dict:

        safety = self._run_isafe(user_message, speed_emotion)
        response = self._run_magic(user_message)
        image_data = self._run_image_gen(user_message)
        health_info = self._run_health_search(user_message)

        _log("Decision", "完成",
            f"emotion={safety['emotion']} → TTS 語調調整")

        return {
            "message": response,
            "emotion": safety["emotion"],
            "is_urgent": safety["is_urgent"],
            "sentiment": safety["sentiment"],
            "trend_alert": safety.get("trend_alert"),
            "elder_id": self.elder_id,
            "history_length": len(self.magic.get_history()),
            "image": image_data,
            "health_info": health_info,
            "persona_name": self.active_persona.get("name", "AI 助理")
        }

    def _run_isafe(self, message: str,
                   speed_emotion: str = "normal") -> dict:
        _log("iSafe", "分析中", f"收到訊息：{message[:20]}...")
        try:
            safety = self.isafe.analyze(message, speed_emotion)
            _log("iSafe", "分析完成",
                 f"emotion={safety['emotion']}, urgent={safety['is_urgent']}")
            return safety
        except Exception as e:
            _log("iSafe", "降級", f"分析失敗，使用預設值：{str(e)[:50]}")
            print(f"iSafe 失敗，降級處理：{e}")
            return {
                "emotion": "normal",
                "is_urgent": False,
                "sentiment": "neutral",
                "should_record": False,
                "reason": "iSafe 降級"
            }

    def _run_magic(self, message: str) -> str:
        _log("Decision", "協調中", "呼叫 MagicAI 生成回應")
        try:
            response = self.magic.chat(message)
            _log("MagicAI", "回應完成", "已儲存對話記憶")
            return response
        except Exception as e:
            _log("MagicAI", "降級", f"回應失敗：{str(e)[:50]}")
            print(f"MagicAI 失敗，降級處理：{e}")
            return "抱歉，我剛剛沒聽清楚，可以再說一次嗎？"

    def _run_image_gen(self, message: str) -> str | None:
        try:
            from backend.tools.image_gen import (
                detect_image_trigger, generate_image
            )
            trigger = detect_image_trigger(message)
            print(f"圖片觸發偵測：message={message[:20]}, trigger={trigger}")
            if not trigger:
                return None
            _log("Decision", "圖片生成",
                 f"偵測到 {trigger} 話題，生成圖片中...")
            image_data = generate_image(message, trigger)
            if image_data:
                _log("Decision", "圖片完成", "圖片生成成功")
            return image_data
        except Exception as e:
            import traceback
            print(f"圖片生成失敗：{e}")
            print(traceback.format_exc())
            return None

    def _run_health_search(self, message: str) -> dict | None:
        try:
            from backend.tools.health_search import HealthSearchService
            health_service = HealthSearchService()
            topic = health_service.detect_health_topic(message)
            if not topic:
                return None
            _log("Decision", "健康搜尋", f"偵測到健康話題：{topic}")
            info = health_service.search_health_info(message, topic)
            if info:
                _log("Decision", "健康搜尋完成",
                     f"找到：{info['title']}")
            return info
        except Exception as e:
            _log("Decision", "健康略過",
                 f"健康搜尋失敗：{str(e)[:50]}")
            print(f"健康搜尋失敗（不影響對話）：{e}")
            return None

    def get_history(self) -> list:
        return self.magic.get_history()

    def get_safety_status(self) -> dict:
        try:
            return self.isafe.get_safety_status()
        except Exception as e:
            print(f"取得安全狀態失敗：{e}")
            return {
                "elder_id": self.elder_id,
                "urgent_count": 0,
                "negative_count": 0,
                "trend_alerts": 0,
                "hazard_level": "low",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M")
            }

    @property
    def profile(self):
        try:
            return self.magic.profile
        except Exception:
            return {}