import asyncio
import collections
import concurrent.futures
import os
import threading
import time
from datetime import datetime
from backend.agents.magic_ai import MagicAI
from backend.agents.i_safe import ISafe, quick_keyword_check

_agent_logs: collections.deque = collections.deque(maxlen=100)
_agent_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("AGENT_EXECUTOR_WORKERS", "4")))
)
_biography_updates_in_progress: set[str] = set()
_biography_updates_lock = threading.Lock()


def _log(agent: str, action: str, detail: str, elder_id: str = None, session_id: str = None, persona_id: str = None):
    _agent_logs.appendleft({
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "action": action,
        "detail": detail,
        "elder_id": elder_id,
        "session_id": session_id,
        "persona_id": persona_id,
    })


def get_logs() -> list:
    return list(_agent_logs)


_magic_agents: dict[str, MagicAI] = {}
_isafe_agents: dict[str, ISafe] = {}
_agents_lock = threading.Lock()


def flush_agent_conversations():
    with _agents_lock:
        snapshot = list(_magic_agents.values())
    for magic in snapshot:
        try:
            if not magic.flush_conversation():
                print(f"對話歷史儲存失敗：{magic.elder_id}")
        except Exception as e:
            print(f"對話歷史儲存失敗：{e}")


def _agent_key(elder_id: str, session_id: str = "default", persona_id: str = None) -> str:
    return f"{elder_id}:{session_id or 'default'}:{persona_id or 'profile'}"


def _get_magic(elder_id: str, session_id: str = "default", persona_id: str = None) -> MagicAI:
    key = _agent_key(elder_id, session_id, persona_id)
    with _agents_lock:
        if key not in _magic_agents:
            _magic_agents[key] = MagicAI(elder_id, persona_id=persona_id)
        return _magic_agents[key]


def _get_isafe(elder_id: str, session_id: str = "default", persona_id: str = None) -> ISafe:
    key = _agent_key(elder_id, session_id, persona_id)
    with _agents_lock:
        if key not in _isafe_agents:
            _isafe_agents[key] = ISafe(elder_id, persona_id=persona_id)
        return _isafe_agents[key]


def clear_agent(elder_id: str, session_id: str = None):
    prefix = f"{elder_id}:{session_id}:" if session_id else f"{elder_id}:"
    with _agents_lock:
        magic_to_flush = []
        for key in list(_magic_agents):
            if key.startswith(prefix):
                magic = _magic_agents.pop(key, None)
                if magic:
                    magic_to_flush.append(magic)
        for key in list(_isafe_agents):
            if key.startswith(prefix):
                _isafe_agents.pop(key, None)
    for magic in magic_to_flush:
        try:
            if not magic.flush_conversation():
                print(f"對話歷史儲存失敗：{elder_id}")
        except Exception as e:
            print(f"對話歷史儲存失敗：{e}")


class Decision:

    def __init__(self, elder_id: str, session_id: str = "default", persona_id: str = None):
        self.chat_count = 0
        self.elder_id = elder_id
        self.session_id = session_id or "default"
        self.persona_id = persona_id
        self.created_at = datetime.now()
        self.last_seen = self.created_at
        self._lock = asyncio.Lock()
        self.magic = _get_magic(elder_id, self.session_id, persona_id)
        self.isafe = _get_isafe(elder_id, self.session_id, persona_id)
        self._setup_persona()

    def _setup_persona(self):
        try:
            from backend.memory.vector_store import VectorMemoryStore
            from backend.services.tts_service import TTSService
            memory = VectorMemoryStore()
            profile = memory.get_profile(self.elder_id)
            personas = profile.get("personas", {})
            active_id = self.persona_id or profile.get("active_persona", "ai")
            active = personas.get(active_id, personas.get("ai", {}))

            self.tts = TTSService()
            voice_path = active.get("voice_path")
            voice_engine = TTSService.normalize_engine(
                active.get("voice_engine", "xtts")
            )
            if voice_engine != "edge":
                self.tts.set_engine(voice_engine, voice_path)
                print(f"TTS 切換為 {voice_engine}，聲音樣本：{voice_path}")
            else:
                self.tts.reset_engine()

            self.active_persona = active
            print(f"人格設定：{active.get('name', 'AI 助理')}")
        except Exception as e:
            print(f"人格設定失敗：{e}")
            from backend.services.tts_service import TTSService
            self.tts = TTSService()
            self.active_persona = {"name": "AI 助理", "honorific": "爺爺"}

    def _log(self, agent: str, action: str, detail: str):
        _log(
            agent, action, detail,
            elder_id=self.elder_id,
            session_id=self.session_id,
            persona_id=self.persona_id or "ai",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def greet(self) -> dict:
        self.last_seen = datetime.now()
        try:
            greeting = self.magic.greet()
            return {
                "message": greeting,
                "emotion": "normal",
                "elder_id": self.elder_id,
                "persona_name": self.active_persona.get("name", "AI 助理"),
            }
        except Exception as e:
            self._log("MagicAI", "錯誤", f"問候失敗：{str(e)[:50]}")
            return {
                "message": "你好！今天感覺怎麼樣呀？",
                "emotion": "normal",
                "elder_id": self.elder_id,
                "persona_name": "AI 助理",
            }

    def chat(self, user_message: str, speed_emotion: str = "normal") -> dict:
        t_chat = time.perf_counter()
        self.last_seen = datetime.now()
        self.chat_count += 1

        if quick_keyword_check(user_message) == 3:
            self._log("Decision", "緊急回應", "關鍵字判定 level=3，跳過一般對話生成")
            try:
                self.isafe.record_emergency(user_message)
            except Exception as e:
                self._log("Decision", "事件儲存失敗", str(e))
            return {
                "message": (
                    "這可能是緊急狀況。請先不要移動，立即呼叫附近照護人員"
                    "或撥打 119。"
                ),
                "emotion": "urgent",
                "is_urgent": True,
                "sentiment": "negative",
                "trend_alert": None,
                "escalation_level": 3,
                "elder_id": self.elder_id,
                "history_length": len(self.magic.get_history()),
                "image": None,
                "image_caption": None,
                "health_info": None,
                "persona_name": self.active_persona.get("name", "AI 助理"),
                "_isafe_ms": None,
                "_magic_ms": None,
                "_chat_total_ms": round((time.perf_counter() - t_chat) * 1000),
                "_llm_used": False,
                "_isafe_path": "emergency_keyword",
            }

        use_rag = quick_keyword_check(user_message) != 0
        safety_future = _agent_executor.submit(
            self._run_isafe,
            user_message,
            speed_emotion,
        )
        response_future = _agent_executor.submit(self._run_magic, user_message, use_rag)
        safety = safety_future.result()
        magic_result = response_future.result()
        response = magic_result["_text"]

        escalation_level = safety.get("escalation_level", 0)

        # Write iSafe result back into the last model message so the admin view can read it.
        self._patch_last_model_message(escalation_level, safety.get("sentiment", "neutral"))

        if escalation_level >= 2:
            response = (
                f"{response}\n\n"
                "請立即通知附近照護人員確認狀況；若有生命危險，請撥打 119。"
            )

        if escalation_level >= 2:
            self._log("Decision", "分級響應", f"level={escalation_level}，需要通知照護人員")

        self._log("Decision", "完成", f"emotion={safety['emotion']} → TTS 語調調整")

        if self.chat_count % 10 == 0:
            self._schedule_biography_update()

        return {
            "message": response,
            "emotion": safety["emotion"],
            "is_urgent": safety["is_urgent"],
            "sentiment": safety["sentiment"],
            "trend_alert": safety.get("trend_alert"),
            "escalation_level": escalation_level,
            "elder_id": self.elder_id,
            "history_length": len(self.magic.get_history()),
            "image": None,
            "image_caption": None,
            "health_info": None,
            "persona_name": self.active_persona.get("name", "AI 助理"),
            "_isafe_ms": safety.get("_isafe_ms"),
            "_magic_ms": magic_result.get("_magic_ms"),
            "_chat_total_ms": round((time.perf_counter() - t_chat) * 1000),
            "_llm_used": safety.get("_llm_used"),
            "_isafe_path": safety.get("_isafe_path"),
        }

    def stream_chat(
        self,
        user_message: str,
        speed_emotion: str = "normal",
    ):
        t_chat = time.perf_counter()
        self.last_seen = datetime.now()
        self.chat_count += 1

        if quick_keyword_check(user_message) == 3:
            try:
                self.isafe.record_emergency(user_message)
            except Exception as e:
                self._log("Decision", "事件儲存失敗", str(e))
            message = (
                "這可能是緊急狀況，請先保持安全並立即通知照護人員，"
                "必要時撥打 119。"
            )
            yield {"type": "chunk", "chunk": message}
            yield {
                "type": "done",
                "message": message,
                "emotion": "urgent",
                "is_urgent": True,
                "sentiment": "negative",
                "trend_alert": None,
                "escalation_level": 3,
                "elder_id": self.elder_id,
                "history_length": len(self.magic.get_history()),
                "persona_name": self.active_persona.get("name", "AI 助理"),
                "_isafe_ms": None,
                "_magic_ms": None,
                "_first_chunk_ms": round(
                    (time.perf_counter() - t_chat) * 1000
                ),
                "_chat_total_ms": round(
                    (time.perf_counter() - t_chat) * 1000
                ),
                "_llm_used": False,
                "_isafe_path": "emergency_keyword",
            }
            return

        use_rag = quick_keyword_check(user_message) != 0
        safety_future = _agent_executor.submit(
            self._run_isafe,
            user_message,
            speed_emotion,
        )
        magic_started = time.perf_counter()
        first_chunk_ms = None
        chunks = []

        try:
            for chunk in self.magic.stream_chat(user_message, use_rag=use_rag):
                if not chunk:
                    continue
                if first_chunk_ms is None:
                    first_chunk_ms = round(
                        (time.perf_counter() - t_chat) * 1000
                    )
                chunks.append(chunk)
                yield {"type": "chunk", "chunk": chunk}
        except Exception as e:
            self._log("MagicAI", "降級", f"串流失敗：{str(e)[:50]}")
            fallback = "抱歉，我剛剛沒聽清楚，可以再說一次嗎？"
            chunks.append(fallback)
            if first_chunk_ms is None:
                first_chunk_ms = round(
                    (time.perf_counter() - t_chat) * 1000
                )
            yield {"type": "chunk", "chunk": fallback}

        magic_ms = round((time.perf_counter() - magic_started) * 1000)
        safety = safety_future.result()
        escalation_level = safety.get("escalation_level", 0)

        # Write iSafe result back into the last model message so the admin view can read it.
        self._patch_last_model_message(escalation_level, safety.get("sentiment", "neutral"))

        response = "".join(chunks)

        if escalation_level >= 2:
            warning = (
                "\n\n請立即通知照護人員；若症狀持續或情況危急，"
                "請撥打 119。"
            )
            response += warning
            yield {"type": "chunk", "chunk": warning}

        if self.chat_count % 10 == 0:
            self._schedule_biography_update()

        yield {
            "type": "done",
            "message": response,
            "emotion": safety["emotion"],
            "is_urgent": safety["is_urgent"],
            "sentiment": safety["sentiment"],
            "trend_alert": safety.get("trend_alert"),
            "escalation_level": escalation_level,
            "elder_id": self.elder_id,
            "history_length": len(self.magic.get_history()),
            "persona_name": self.active_persona.get("name", "AI 助理"),
            "_isafe_ms": safety.get("_isafe_ms"),
            "_magic_ms": magic_ms,
            "_first_chunk_ms": first_chunk_ms,
            "_chat_total_ms": round(
                (time.perf_counter() - t_chat) * 1000
            ),
            "_llm_used": safety.get("_llm_used"),
            "_isafe_path": safety.get("_isafe_path"),
        }

    def _patch_last_model_message(self, escalation_level: int, sentiment: str) -> None:
        """Write iSafe results back into the most recent model message in conversation_history."""
        for msg in reversed(self.magic.get_history()):
            if msg.get("role") == "model":
                msg["escalation_level"] = escalation_level
                msg["sentiment"] = sentiment
                break

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
        t0 = time.perf_counter()
        self._log("iSafe", "分析中", f"收到訊息：{message[:20]}...")
        try:
            safety = self.isafe.analyze(message, speed_emotion)
            safety["_isafe_ms"] = round((time.perf_counter() - t0) * 1000)
            self._log("iSafe", "分析完成",
                      f"emotion={safety['emotion']}, urgent={safety['is_urgent']}")
            return safety
        except Exception as e:
            self._log("iSafe", "降級", f"分析失敗，使用預設值：{str(e)[:50]}")
            print(f"iSafe 失敗，降級處理：{e}")
            return {
                "emotion": "normal",
                "is_urgent": False,
                "sentiment": "neutral",
                "should_record": False,
                "reason": "iSafe 降級",
                "_llm_used": True,
                "_isafe_path": "llm_error",
                "_isafe_ms": round((time.perf_counter() - t0) * 1000),
            }

    def _run_magic(self, message: str, use_rag: bool = True) -> dict:
        t0 = time.perf_counter()
        self._log("Decision", "協調中", "呼叫 MagicAI 生成回應")
        try:
            response = self.magic.chat(message, use_rag=use_rag)
            self._log("MagicAI", "回應完成", "已儲存對話記憶")
            return {
                "_text": response,
                "_magic_ms": round((time.perf_counter() - t0) * 1000),
            }
        except Exception as e:
            self._log("MagicAI", "降級", f"回應失敗：{str(e)[:50]}")
            print(f"MagicAI 失敗，降級處理：{e}")
            return {
                "_text": "抱歉，我剛剛沒聽清楚，可以再說一次嗎？",
                "_magic_ms": round((time.perf_counter() - t0) * 1000),
            }

    def _run_image_gen(self, message: str) -> tuple[str | None, str | None]:
        try:
            from backend.tools.image_gen import detect_image_trigger, generate_image
            trigger = detect_image_trigger(message)
            print(f"圖片觸發偵測：message={message[:20]}, trigger={trigger}")
            if not trigger:
                return None, None

            self._log("Decision", "圖片生成", "偵測到場景，生成圖片中...")
            image_data = generate_image(message, trigger)
            if not image_data:
                return None, None

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

            self._log("Decision", "圖片完成", "圖片生成成功")
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
            self._log("Decision", "健康搜尋", f"偵測到健康話題：{topic}")
            info = health_service.search_health_info(message, topic)
            if info:
                self._log("Decision", "健康搜尋完成", f"找到：{info['title']}")
            return info
        except Exception as e:
            self._log("Decision", "健康略過", f"健康搜尋失敗：{str(e)[:50]}")
            print(f"健康搜尋失敗（不影響對話）：{e}")
            return None

    # ------------------------------------------------------------------
    # Periodic biography update
    # ------------------------------------------------------------------

    def _schedule_biography_update(self):
        with _biography_updates_lock:
            if self.elder_id in _biography_updates_in_progress:
                return
            _biography_updates_in_progress.add(self.elder_id)

        future = _agent_executor.submit(self._update_biography)

        def complete(completed_future):
            try:
                completed_future.result()
                self._log(
                    "Decision",
                    "生平更新",
                    f"第 {self.chat_count} 次對話，完成生平文章更新",
                )
            except Exception as e:
                print(f"生平更新失敗：{e}")
            finally:
                with _biography_updates_lock:
                    _biography_updates_in_progress.discard(self.elder_id)

        future.add_done_callback(complete)

    def _update_biography(self):
        from backend.memory.vector_store import VectorMemoryStore

        memory = VectorMemoryStore()
        profile = memory.get_profile(self.elder_id)
        if not profile:
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

        if not biography or len(biography) <= 50:
            return

        if existing_bio:
            # Verify that key facts from the profile still appear in the new bio.
            key_facts = [f for f in [
                name,
                profile.get("persona", {}).get("former_job"),
                *(p.get("name") for pid, p in profile.get("personas", {}).items() if pid != "ai"),
            ] if f]
            missing = [fact for fact in key_facts if fact and fact not in biography]
            if missing or len(biography) < len(existing_bio) * 0.7:
                print(f"生平更新品質不佳（缺少事實：{missing}），放棄更新：{name}")
                return

        biography_data = {
            "content": biography,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": profile.get("elder_biography", {}).get("sources", []),
            "manually_edited": False,
        }
        update_result = memory.set_biography(
            self.elder_id,
            biography_data,
            skip_if_manual=True,
        )
        if update_result == "skipped":
            return
        if update_result == "failed":
            raise RuntimeError("生平文章儲存失敗")
        print(f"生平文章已更新：{name}")
