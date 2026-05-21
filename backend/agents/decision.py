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
        self.chat_count = 0
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

            if engine == "breezyvoice":
                self.tts.set_engine("breezyvoice", voice_path)
                print(f"TTS 切換為 BreezyVoice，聲音樣本：{voice_path}")
            elif engine == "edge":
                self.tts.reset_engine()
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
        self.chat_count += 1

        safety = self._run_isafe(user_message, speed_emotion)
        response = self._run_magic(user_message)
        image_data, image_caption = self._run_image_gen(user_message)
        escalation_level = safety.get("escalation_level", 0)
        health_info = None if escalation_level >= 2 else self._run_health_search(user_message)

        _log("Decision", "完成",
            f"emotion={safety['emotion']} → TTS 語調調整")

        escalation_level = safety.get("escalation_level", 0)
        if escalation_level >= 2:
            _log("Decision", "分級響應", f"level={escalation_level}，需要通知照護人員")

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

    def _run_image_gen(self, message: str) -> tuple[str | None, str | None]:
        try:
            from backend.tools.image_gen import (
                detect_image_trigger, generate_image
            )
            trigger = detect_image_trigger(message)
            print(f"圖片觸發偵測：message={message[:20]}, trigger={trigger}")
            if not trigger:
                return None, None
            _log("Decision", "圖片生成", f"偵測到場景，生成圖片中...")
            image_data = generate_image(message, trigger)
            if not image_data:
                return None, None

            # 根據人格身份生成引導語
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
    def _update_biography(self):
        """每 10 次對話後，把 recent_events 加進生平文章重新彙整"""
        from backend.memory.vector_store import VectorMemoryStore
        from google import genai
        from google.genai import types
        import os
        from datetime import datetime

        memory = VectorMemoryStore()
        profile = memory.get_profile(self.elder_id)
        if not profile:
            return

        if profile.get("elder_biography", {}).get("manually_edited"):
            return

        name = profile.get("name", "長者")
        existing_bio = profile.get("elder_biography", {}).get("content", "")
        recent_events = profile.get("recent_events", [])
        family_notes = profile.get("family_notes", [])

        important_events = [
            e for e in recent_events
            if e.get("importance", 0) >= 0.7
        ][-10:]

        if not important_events and not family_notes:
            print(f"無足夠重要資訊，跳過生平更新：{name}")
            return

        events_text = "\n".join([
            f"- {e.get('event', '')}（依據：{e.get('reason', '')}）"
            for e in important_events
        ]) if important_events else "無"

        # Python 層粗篩（整句比對），語意去重交給 LLM
        filtered_notes = [
            n for n in family_notes
            if not (existing_bio and n.get("note", "") in existing_bio)
        ]
        family_notes_text = "\n".join([
            f"- {n.get('note', '')}" for n in filtered_notes
        ]) if filtered_notes else "無"

        prompt = f"""你是一個長照系統的資深生平檔案維護模組。
    請根據最新收集到的生活動態與家人筆記，優化並更新該長者的生平介紹文章。

    長者姓名：{name}

    【現有生平介紹】
    {existing_bio if existing_bio else '尚無'}

    【近期對話中提煉出的高價值新資訊】
    {events_text}

    【家人最新提供的照護備忘錄】
    {family_notes_text}

    【更新與重構規則 — 請嚴格遵守】
    1. 事實不可磨滅：現有生平中記錄的生命事實（職業、榮譽、家族結構、重要歷史記憶）絕對不可刪除。
    2. 自然語意融合：你被允許改寫現有文句的結構，將新資訊流暢地編織進文章中，避免在末尾盲目堆疊附註。
    3. 語意去重：若新資訊已在現有生平中被提及，維持原狀，不重複撰寫。
    4. 矛盾處理：若長者自述與現有生平或家人資訊衝突，以現有生平與家人資訊為準。長者的混亂記憶用「長者有時會提及...」方式溫柔附註。
    5. 若無有價值的新資訊，直接回傳現有生平原文，不做任何修改。
    6. 繁體中文、第三人稱，維持像老朋友介紹般自然溫暖的台灣口吻。
    7. 只回傳更新後的文章本體，不要任何標題、前言或說明。"""

        try:
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=1000,
                )
            )

            biography = response.text.strip()

            if biography and len(biography) > 50:
                # 驗證：新生平必須保留舊生平的關鍵內容
                if existing_bio:
                    existing_words = set(existing_bio[:50])
                    new_words = set(biography[:100])
                    overlap = len(existing_words & new_words)
                    if overlap < 5 or len(biography) < len(existing_bio) * 0.8:
                        print(f"生平更新品質不佳，放棄更新：{name}")
                        return

                profile["elder_biography"] = {
                    "content": biography,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "sources": profile.get("elder_biography", {}).get("sources", []),
                    "manually_edited": False
                }
                memory._save(self.elder_id, profile)
                print(f"生平文章已更新：{name}")

        except Exception as e:
            print(f"生平更新失敗：{e}")

    @property
    def profile(self):
        try:
            return self.magic.profile
        except Exception:
            return {}