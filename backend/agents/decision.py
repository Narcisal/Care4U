import collections
from datetime import datetime
from backend.agents.magic_ai import MagicAI
from backend.agents.i_safe import ISafe

_agent_logs: collections.deque = collections.deque(maxlen=100)


def _log(agent: str, action: str, detail: str):
    _agent_logs.appendleft({
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "action": action,
        "detail": detail,
    })


def get_logs() -> list:
    return list(_agent_logs)


_magic_agents: dict[str, MagicAI] = {}
_isafe_agents: dict[str, ISafe] = {}


def _agent_key(elder_id: str, session_id: str = "default", persona_id: str = None) -> str:
    return f"{elder_id}:{session_id or 'default'}:{persona_id or 'profile'}"


def _get_magic(elder_id: str, session_id: str = "default", persona_id: str = None) -> MagicAI:
    key = _agent_key(elder_id, session_id, persona_id)
    if key not in _magic_agents:
        _magic_agents[key] = MagicAI(elder_id, persona_id=persona_id)
    return _magic_agents[key]


def _get_isafe(elder_id: str, session_id: str = "default", persona_id: str = None) -> ISafe:
    key = _agent_key(elder_id, session_id, persona_id)
    if key not in _isafe_agents:
        _isafe_agents[key] = ISafe(elder_id, persona_id=persona_id)
    return _isafe_agents[key]


def clear_agent(elder_id: str, session_id: str = None):
    prefix = f"{elder_id}:{session_id or ''}"
    for key in list(_magic_agents):
        if key.startswith(prefix):
            _magic_agents.pop(key, None)
    for key in list(_isafe_agents):
        if key.startswith(prefix):
            _isafe_agents.pop(key, None)


class Decision:

    def __init__(self, elder_id: str, session_id: str = "default", persona_id: str = None):
        self.chat_count = 0
        self.elder_id = elder_id
        self.session_id = session_id or "default"
        self.persona_id = persona_id
        self.magic = _get_magic(elder_id, self.session_id, persona_id)
        self.isafe = _get_isafe(elder_id, self.session_id, persona_id)
        self._setup_persona()

    def _setup_persona(self):
        """Configure TTS engine from the active persona."""
        try:
            from backend.memory.vector_store import VectorMemoryStore
            from backend.services.tts_service import TTSService
            memory = VectorMemoryStore()
            profile = memory.get_profile(self.elder_id)
            personas = profile.get("personas", {})
            active_id = self.persona_id or profile.get("active_persona", "ai")
            active = personas.get(active_id, personas.get("ai", {}))

            self.tts = TTSService()
            engine = active.get("voice_engine", "xtts")
            voice_path = active.get("voice_path")

            if voice_path:
                self.tts.set_engine("xtts", voice_path)
                print(f"TTS 切換為 XTTS，聲音樣本：{voice_path}")
            else:
                self.tts.reset_engine()

            self.active_persona = active
            print(f"人格設定：{active.get('name', 'AI 助理')}")
        except Exception as e:
            print(f"人格設定失敗：{e}")
            from backend.services.tts_service import TTSService
            self.tts = TTSService()
            self.active_persona = {"name": "AI 助理", "honorific": "爺爺"}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def greet(self) -> dict:
        try:
            greeting = self.magic.greet()
            return {
                "message": greeting,
                "emotion": "normal",
                "elder_id": self.elder_id,
                "persona_name": self.active_persona.get("name", "AI 助理"),
            }
        except Exception as e:
            _log("MagicAI", "錯誤", f"問候失敗：{str(e)[:50]}")
            return {
                "message": "你好！今天感覺怎麼樣呀？",
                "emotion": "normal",
                "elder_id": self.elder_id,
                "persona_name": "AI 助理",
            }

    def chat(self, user_message: str, speed_emotion: str = "normal") -> dict:
        self.chat_count += 1

        safety = self._run_isafe(user_message, speed_emotion)
        response = self._run_magic(user_message)
        image_data, image_caption = self._run_image_gen(user_message)

        escalation_level = safety.get("escalation_level", 0)
        if escalation_level >= 2:
            _log("Decision", "分級響應", f"level={escalation_level}，需要通知照護人員")

        health_info = None if escalation_level >= 2 else self._run_health_search(user_message)

        _log("Decision", "完成", f"emotion={safety['emotion']} → TTS 語調調整")

        if self.chat_count % 10 == 0:
            try:
                self._update_biography()
                _log("Decision", "生平更新", f"第 {self.chat_count} 次對話，更新生平文章")
            except Exception as e:
                print(f"生平更新失敗：{e}")

        return {
            "message": response,
            "emotion": safety["emotion"],
            "is_urgent": safety["is_urgent"],
            "sentiment": safety["sentiment"],
            "trend_alert": safety.get("trend_alert"),
            "escalation_level": escalation_level,
            "elder_id": self.elder_id,
            "history_length": len(self.magic.get_history()),
            "image": image_data,
            "image_caption": image_caption,
            "health_info": health_info,
            "persona_name": self.active_persona.get("name", "AI 助理"),
        }

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
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }

    @property
    def profile(self):
        try:
            return self.magic.profile
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Sub-agent runners
    # ------------------------------------------------------------------

    def _run_isafe(self, message: str, speed_emotion: str = "normal") -> dict:
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
                "reason": "iSafe 降級",
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

    def _run_image_gen(self, message: str) -> tuple[str | None, str | None]:
        try:
            from backend.tools.image_gen import detect_image_trigger, generate_image
            trigger = detect_image_trigger(message)
            print(f"圖片觸發偵測：message={message[:20]}, trigger={trigger}")
            if not trigger:
                return None, None

            _log("Decision", "圖片生成", "偵測到場景，生成圖片中...")
            image_data = generate_image(message, trigger)
            if not image_data:
                return None, None

            persona_name = self.active_persona.get("name", "AI 助理")
            honorific = self.active_persona.get("honorific", "爺爺")
            relation = self.active_persona.get("relation", "")

            if relation in ["女兒", "媳婦"]:
                caption = f"{honorific}，我剛才幫你畫了一張，你看看有沒有像你說的那個地方？"
            elif relation in ["孫女", "孫子", "外孫女", "外孫"]:
                caption = f"{honorific}！我剛畫了一幅畫，你看看像不像！"
            elif relation in ["兒子", "女婿"]:
                caption = f"{honorific}，我剛幫你畫了一張，你看看有沒有像？"
            else:
                caption = f"{honorific}，我剛幫你畫了一幅畫，你看看像不像你說的那個地方？"

            _log("Decision", "圖片完成", "圖片生成成功")
            return image_data, caption
        except Exception as e:
            import traceback
            print(f"圖片生成失敗：{e}")
            print(traceback.format_exc())
            return None, None

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
                _log("Decision", "健康搜尋完成", f"找到：{info['title']}")
            return info
        except Exception as e:
            _log("Decision", "健康略過", f"健康搜尋失敗：{str(e)[:50]}")
            print(f"健康搜尋失敗（不影響對話）：{e}")
            return None

    # ------------------------------------------------------------------
    # Periodic biography update
    # ------------------------------------------------------------------

    def _update_biography(self):
        """Merge recent high-importance events into the elder's biography."""
        from backend.memory.vector_store import VectorMemoryStore

        memory = VectorMemoryStore()
        profile = memory.get_profile(self.elder_id)
        if not profile:
            return

        if profile.get("elder_biography", {}).get("manually_edited"):
            return

        name = profile.get("name", "長者")
        existing_bio = profile.get("elder_biography", {}).get("content", "")
        important_events = [
            e for e in profile.get("recent_events", [])
            if e.get("importance", 0) >= 0.7
        ][-10:]
        family_notes = profile.get("family_notes", [])

        if not important_events and not family_notes:
            print(f"無足夠重要資訊，跳過生平更新：{name}")
            return

        biography = self.magic.llm.update_biography(
            name=name,
            existing_bio=existing_bio,
            important_events=important_events,
            family_notes=family_notes,
        )

        if biography and len(biography) > 50:
            # Sanity-check: new bio must preserve the opening content of old bio
            if existing_bio:
                existing_words = set(existing_bio[:50])
                new_words = set(biography[:100])
                if len(existing_words & new_words) < 5 or len(biography) < len(existing_bio) * 0.8:
                    print(f"生平更新品質不佳，放棄更新：{name}")
                    return

            profile["elder_biography"] = {
                "content": biography,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sources": profile.get("elder_biography", {}).get("sources", []),
                "manually_edited": False,
            }
            memory._save(self.elder_id, profile)
            print(f"生平文章已更新：{name}")
