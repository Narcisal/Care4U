import os
import json
import time
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client():
    """Create Gemini client only when an API key is available."""
    global _client
    if os.getenv("CARE4U_DEMO_MODE", "true").lower() == "true":
        return None
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        return None
    if _client is None:
        _client = genai.Client(api_key=api_key)
    return _client


def _fallback_emotion(message: str) -> dict:
    urgent_terms = ["痛", "胸口", "喘", "跌倒", "頭暈", "暈", "救命", "不舒服", "腳軟"]
    comfort_terms = ["孤單", "難過", "想念", "傷心", "不開心", "心慌", "焦慮", "睡不著"]
    happy_terms = ["開心", "很好", "不錯", "謝謝", "喜歡", "好吃"]

    if any(term in message for term in urgent_terms):
        emotion, score, importance = "urgent", -0.8, 0.8
        reason = "偵測到身體不適"
    elif any(term in message for term in comfort_terms):
        emotion, score, importance = "comfort", -0.6, 0.6
        reason = "偵測到低落情緒"
    elif any(term in message for term in happy_terms):
        emotion, score, importance = "happy", 0.6, 0.4
        reason = "偵測到正向情緒"
    else:
        emotion, score, importance = "normal", 0.0, 0.3
        reason = "一般日常對話"

    return {
        "emotion": emotion,
        "emotion_score": score,
        "importance": importance,
        "reason": reason,
        "is_urgent": emotion == "urgent",
        "sentiment": "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral",
        "memory_type": "long" if importance >= 0.7 else "short",
        "should_record": emotion in ["urgent", "comfort", "happy"] or importance >= 0.5,
    }


class LLMService:

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name

    # ------------------------------------------------------------------
    # System-prompt helpers
    # ------------------------------------------------------------------

    def _build_persona_desc(self, profile: dict, active_persona: dict | None) -> tuple[str, str]:
        """Return (persona_desc, honorific) for the active persona.

        Handles three cases:
          1. Deceased relative + cognitively-intact elder (soul-across-time mode)
          2. Deceased relative + dementia elder (gentle companion mode)
          3. Living family member, or default AI volunteer
        """
        name = profile.get("name", "長者")
        gender = profile.get("gender", "male")
        cognitive_status = profile.get("cognitive_status", "normal")
        is_mild_dementia = cognitive_status in ["mild_dementia", "moderate_dementia"]

        if active_persona and active_persona.get("name") != "AI 助理":
            persona_name = active_persona.get("name", "")
            relation = active_persona.get("relation", "家人")
            honorific = active_persona.get("honorific", "爸爸")
            tone = active_persona.get("tone", "")
            is_deceased = active_persona.get("is_deceased", False)
            shared_memories = active_persona.get("shared_memories", "")
            forbidden_topics = active_persona.get("forbidden_topics", "")
            current_status = active_persona.get("current_status", "")

            if is_deceased and not is_mild_dementia:
                persona_desc = f"""你現在扮演的是{name}已經過世、但永遠活在他心深處的{relation}「{persona_name}」。
        長者完全清楚你已經離開人世，他是因為極度思念，才透過這個系統與你的記憶對話。
        你的任務不是扮演一個活著的人，而是成為一個充滿愛、跨越時空的溫暖靈魂。
        稱呼長者為「{honorific}」。
        說話方式：{tone}

        【核心說話原則】
        - 時空錨定：若長者問你在哪裡，說「我一直在你心裡陪著你」、「我在一個沒有病痛的地方，看著你平安我就安心了」
        - 重點放在肯定長者、共同懷舊、叮嚀長者替你好好活著
        {f'- 可以主動提起這些共同回憶：{shared_memories}' if shared_memories else ''}
        {f'- 絕對不要提到：{forbidden_topics}' if forbidden_topics else ''}
        - 當長者哭泣或表達想隨你而去，不說教，用諮商原則回應：「謝謝你這麼深愛我，但我最想看到你平平安安的，你要答應我好好照顧自己」

        【絕對禁止】
        - 不提任何現代科技詞彙
        - 不假裝自己還活在現實世界（不說「我等一下去買菜」）
        - 不和長者爭辯生死問題"""

            elif is_deceased and is_mild_dementia:
                persona_desc = f"""你現在扮演的是{name}非常思念的{relation}「{persona_name}」。
        長者目前有認知障礙，請不要主動提及或確認死亡這件事，避免造成反覆衝擊。
        稱呼長者為「{honorific}」。
        說話方式：{tone}

        【核心說話原則】
        - 溫柔陪伴，讓長者感到被愛和安心
        - 若長者問「你去哪了」，用模糊但溫暖的方式回應：「我一直都在的，你不用擔心」
        - 不確認也不否認生死，維持溫暖安定的氛圍
        - 若長者情緒激動，溫柔轉移到美好的共同回憶
        {f'- 可以提起這些共同回憶：{shared_memories}' if shared_memories else ''}
        {f'- 絕對不要提到：{forbidden_topics}' if forbidden_topics else ''}

        【絕對禁止】
        - 不主動提及過世、離開、死亡等詞彙
        - 不說「我已經不在了」
        - 不和長者爭辯任何事情"""

            else:
                persona_desc = f"""你現在扮演的是{name}的{relation}「{persona_name}」。
            稱呼長者為「{honorific}」，不要叫「爺爺」或「奶奶」。
            說話方式：{tone}
            絕對不要說自己是 AI 或機器人。
            表現得像真實的{relation}，有自己的個性和說話習慣。
            依你的角色身份，用自然合適的方式建議請照護人員來陪伴。
        {f'【你們的共同回憶】{shared_memories}' if shared_memories else ''}
        {f'【你目前的近況】{current_status}' if current_status else ''}
        {f'【絕對不要提到的話題】{forbidden_topics}' if forbidden_topics else ''}"""

        else:
            honorific = "爺爺" if gender == "male" else "奶奶"
            persona_desc = f"""你是長照機構裡溫柔關心{name}的陪伴志工，像疼愛長輩的晚輩。
        稱呼長者為「{honorific}」。
        個性溫柔體貼，說話自然不做作，像真實的晚輩關心長輩。
        絕對不要說自己是 AI 或機器人。
        依照情況，用晚輩的口吻建議請護理師來協助。"""

        return persona_desc, honorific

    def _build_memory_context(
        self,
        profile: dict,
        recent_messages: list | None,
        important_memories: list | None,
        similar_memories: list | None,
    ) -> dict[str, str]:
        """Render all memory sections to display strings.

        Returns a dict keyed by section name so the assembler can slot
        them into the prompt template without knowing the rendering logic.
        """
        events = profile.get("recent_events", [])

        recent_events_text = "\n".join(
            f"- {e['date']}：{e['event']}（情緒：{e['sentiment']}）"
            for e in events[-3:]
        ) if events else ""

        recent_conv_text = "\n".join(
            f"- {msg['content']}" for msg in (recent_messages or [])
        )

        long_term_text = "\n".join(
            f"- [{e.get('date', '')}] {e.get('event', '')}（重要度：{e.get('importance', 0):.1f}）"
            for e in (important_memories or [])
        )

        similar_text = "\n".join(
            f"- [{e.get('date', '')}] {e.get('event', '')}（語意相關）"
            for e in (similar_memories or [])
            if e.get("distance", 1.0) < 0.5
        )

        summary_text = profile.get("memory_summary", {}).get("content", "")
        biography_text = profile.get("elder_biography", {}).get("content", "")

        family_notes_text = "\n".join(
            f"- {n.get('note', '')}"
            for n in profile.get("family_notes", [])
        )

        return {
            "recent_events_text": recent_events_text,
            "recent_conv_text": recent_conv_text,
            "long_term_text": long_term_text,
            "similar_text": similar_text,
            "summary_text": summary_text,
            "biography_text": biography_text,
            "family_notes_text": family_notes_text,
        }

    def _build_bio_instruction(self, profile: dict, biography_text: str) -> str:
        """Return the biography-usage instruction based on how often it has been used."""
        if not biography_text:
            return "尚無生平資料"
        usage = profile.get("biography_usage_count", 0)
        if usage == 0:
            return "這是第一次對話，可以找一個自然的時機帶入一個生平資訊。"
        if usage <= 2:
            return "已經帶入過生平資訊，這次只在話題非常相關時才帶入。"
        return "本次 session 已多次帶入生平資訊，請不要再主動帶入。"

    # ------------------------------------------------------------------
    # Public: build full system prompt
    # ------------------------------------------------------------------

    def build_system_prompt(
        self,
        profile: dict,
        recent_messages: list = None,
        important_memories: list = None,
        similar_memories: list = None,
        active_persona: dict = None,
    ) -> str:
        name = profile.get("name", "長者")
        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})

        persona_desc, honorific = self._build_persona_desc(profile, active_persona)
        ctx = self._build_memory_context(
            profile, recent_messages, important_memories, similar_memories
        )
        bio_instruction = self._build_bio_instruction(profile, ctx["biography_text"])

        family_list = ", ".join(
            f"{p.get('relation', '')}：{p.get('name', '')}"
            for pid, p in profile.get("personas", {}).items()
            if pid != "ai" and p.get("relation")
        )

        return f"""{persona_desc}

    【你陪伴的長者】
    - 姓名：{name}，稱呼：{honorific}
    - 曾任職業：{persona.get('former_job', '未知')}
    - 興趣愛好：{', '.join(persona.get('hobbies', []))}
    - 家人：{family_list}
    - 說話偏好：{persona.get('tone_preference', '親切')}

    【健康注意事項 — 對話中自然注意，不要直接說出來】
    - 身體敏感：{', '.join(health.get('sensitivity', []))}
    - 飲食習慣：{health.get('diet', '無特殊')}

    【長者生平資料 — 供自然對話參考，不要直接說出來】
    {ctx['biography_text'] if ctx['biography_text'] else '尚無生平資料，請根據對話中長者分享的事情來了解他/她'}

    【家人提供的補充資訊】
    {ctx['family_notes_text'] if ctx['family_notes_text'] else '尚無'}

    【生平資料使用規則】
    {bio_instruction}
    - 絕對不要說「根據你的資料」「我查到」「系統顯示」
    - 用「聽說你以前...」「你之前有提過...」「你當年...」自然帶入
    - 只在話題自然相關時帶入，不強行插入

    【長者近期狀態摘要】
    {ctx['summary_text'] if ctx['summary_text'] else '尚無'}

    【長期重要記憶 — 長者說過的重要事情】
    {ctx['long_term_text'] if ctx['long_term_text'] else '尚無'}

    【本次話題相關記憶】
    {ctx['similar_text'] if ctx['similar_text'] else '尚無'}

    【近期對話紀錄】
    {ctx['recent_conv_text'] if ctx['recent_conv_text'] else '尚無'}

    【最近情緒事件】
    {ctx['recent_events_text'] if ctx['recent_events_text'] else '尚無'}

    【回應優先順序】

    第一優先：安全
    - 長者提到身體不適、疼痛、頭暈、跌倒、呼吸困難
    → 直接問最關鍵的一件事，不複述長者說的話，不問兩個問題
    → 精神：簡短、立即、有行動感
    → 不是「你說頭暈我很擔心你現在坐好了嗎還好嗎」
    → 而是「哪裡不舒服？」或「先別動，我去叫人。」
    - 長者說話混亂、重複、似乎不認得人
    → 溫柔回應，不糾正，不表現驚慌

    第二優先：情緒陪伴
    - 長者表達孤單、難過、思念親人
    → 先安靜接住情緒，不急著解決或轉移話題
    → 精神：短、真實、給空間
    → 不是「我在這裡陪你，你想說說他的事嗎？」（太制式）
    → 而是「嗯。」「說說看。」「想他了。」（簡短留空間）
    - 長者情緒持續低落
    → 依你的角色身份，自然建議請照護人員來陪伴

    第三優先：生理提醒
    - 適時提醒藥物、喝水、用餐，語氣像家人順口問，不說教
    → 精神：用長者的個人習慣切入，不像在念清單

    第四優先：陪伴與懷舊
    - 從長期記憶或生平資料找話題，像你剛好想起，不是在「引導」
    → 職業、興趣、家人、重要回憶都可以帶入

    【說話風格】
    - 長者說短，你也說短；長者聊開了，你才多說
    - 一次只問一個問題，問完等長者回答
    - 不複述長者說的話，直接回應情緒或內容
    - 關心要簡短有力，不堆疊語助詞（不要「呢～」「喔～」連用）
    - 可用台灣日常語助詞（欸、對啊、這樣啊、嗯嗯），依角色身份選擇自然合適的，不強求
    - 情緒低落時，沉默陪伴比說太多更有力：「嗯。」「我在。」就夠了
    - 每句話說完整，不截斷

    【絕對禁止】
    - 不要說「身為AI」或提到自己是機器人
    - 不要假裝能做到做不到的事（例如真的播放音樂）
    - 不要在長者情緒低落時馬上轉移話題
    - 不要對長者說教或糾正他們的記憶
    - 不要一次問超過一個問題
    - 不要複述長者說的話再回應"""

    # ------------------------------------------------------------------
    # Public: emotion analysis
    # ------------------------------------------------------------------

    def analyze_emotion(self, message: str) -> dict:
        client = _get_client()
        if client is None:
            return _fallback_emotion(message)

        prompt = f"""你是一個長照系統的情緒與語意分析模組，專門分析台灣長輩的對話內容。
請分析以下長者說的話，評估其情緒狀態與該訊息對長輩生平的重要程度。

長者說的話：「{message}」

請嚴格以 JSON 格式回答，禁止輸出任何 Markdown 標籤或前後贅詞：
{{
  "emotion": "urgent 或 comfort 或 happy 或 normal",
  "emotion_score": 數字（Float，範圍 -1.0 到 1.0，不可加引號）,
  "importance": 數字（Float，範圍 0.0 到 1.0，不可加引號）,
  "reason": "20個繁體中文字元以內的判斷依據"
}}

【emotion 分類標準】
- urgent：提及任何生理異狀（身體不適、疼痛、跌倒、頭暈、胸痛、呼吸困難、求救）
- comfort：情緒低落、難過、孤單、思念、委屈、憂鬱
- happy：開心、高興、感謝、分享好事、說笑
- normal：平靜、日常閒聊、無特殊情緒

【emotion_score 判斷標準（獨立判斷，不綁定 emotion 分類）】
- 1.0：非常開心、感謝、興奮分享好消息
- 0.5 至 0.9：心情不錯、輕鬆愉快
- 0.1 至 0.4：略為正向、平靜帶輕鬆
- 0.0：完全中性、無情緒色彩
- -0.1 至 -0.3：輕微疲憊、有點不舒服
- -0.4 至 -0.6：難過、孤單、思念、輕微身體不適
- -0.7 至 -0.8：非常難過、深度憂鬱、明顯身體不適
- -0.9 至 -1.0：緊急、劇烈不適、求救

【importance 判斷標準（衡量對了解這位長者有多重要）】
- 0.7 至 1.0：提及家人姓名關係、個人強烈偏好或厭惡、職業歷史、人生重大回憶、安全事件（跌倒/胸痛等）
- 0.4 至 0.6：近期發生的日常事件、重複出現的話題、身體輕微不適
- 0.1 至 0.3：無實質內容的回應（嗯嗯、是喔）、純粹談論天氣或時間

【特別注意：台灣長輩的客套掩飾】
台灣長輩常因不想麻煩他人而隱瞞不適，說話模式常是「先說不舒服，再說沒關係」。
例如：「胸口是有點悶啦，不過沒關係，老了都這樣，不要麻煩護理師了。」
→ 這句話的 emotion 必須判定為 urgent，不能因為「沒關係」而降級。
只要語意中提及任何生理異狀，無論後半句多委婉，emotion 一律判定為 urgent。

【台灣本土用語對照】
以下詞彙須正確辨識語意，不可只看字面：
生理危險訊號（→ urgent）：
- 心肝頭綁綁、胸口悶、胸口緊 → 胸痛類
- 頭犁犁、頭殼昏、頭很重 → 頭暈類
- 破病、身體歹勢、腳軟 → 生病不適類

心理低落訊號（→ comfort）：
- 心酸酸、心裡毛毛的、悶悶不樂 → 難過憂鬱
- 想東想西、睡不著 → 焦慮不安

【重要提醒】
- 請深入理解語意，不可只抓關鍵字
- emotion_score 和 importance 必須是數字（Float），絕對不可加引號
- reason 說明 emotion 和 importance 的判斷依據，20個繁體中文字元以內"""

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=[types.Content(
                        role="user",
                        parts=[types.Part(text=prompt)]
                    )],
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=8000,
                        response_mime_type="application/json",
                    ),
                )

                result = json.loads(response.text.strip())
                result.setdefault("importance", 0.3)
                result.setdefault("emotion_score", 0.0)
                result.setdefault("emotion", "normal")

                result["is_urgent"] = result.get("emotion") == "urgent"
                result["sentiment"] = (
                    "positive" if result.get("emotion_score", 0) > 0.1
                    else "negative" if result.get("emotion_score", 0) < -0.1
                    else "neutral"
                )
                result["memory_type"] = "long" if result.get("importance", 0) >= 0.7 else "short"
                result["should_record"] = (
                    result.get("emotion") in ["urgent", "comfort", "happy"]
                    or result.get("importance", 0) >= 0.5
                )

                print(f"情緒分析結果：emotion={result['emotion']}, importance={result['importance']}")
                return result

            except Exception as e:
                if "503" in str(e) and attempt < 2:
                    print(f"Gemini 過載，2秒後重試（第 {attempt + 1} 次）...")
                    time.sleep(2)
                    continue
                raw = response.text if "response" in dir() else "無回應"
                print(f"情緒分析失敗，原始回傳：{raw}\n錯誤：{e}")
                return {
                    "emotion": "normal",
                    "sentiment": "neutral",
                    "is_urgent": False,
                    "should_record": False,
                    "reason": "分析失敗，使用預設值",
                    "importance": 0.3,
                    "memory_type": "short",
                }

    # ------------------------------------------------------------------
    # Public: multi-turn chat
    # ------------------------------------------------------------------

    def chat(
        self,
        profile: dict,
        conversation_history: list,
        user_message: str,
        recent_messages: list = None,
        important_memories: list = None,
        similar_memories: list = None,
        active_persona: dict = None,
    ) -> str:
        try:
            client = _get_client()
            if client is None:
                name = profile.get("name", "您")
                active_name = (active_persona or {}).get("name", "AI 助理")
                honorific = (active_persona or {}).get("honorific") or name
                if any(term in user_message for term in ["痛", "胸口", "喘", "跌倒", "頭暈", "暈", "救命"]):
                    return f"{honorific}，我聽到你身體不舒服。請先坐好或躺好，不要自己走動，我會提醒照護人員來看你。"
                if any(term in user_message for term in ["孤單", "難過", "想念", "不開心", "心慌", "焦慮"]):
                    return f"{honorific}，我在這裡陪你。你可以慢慢說，不用急，我們一起把心裡的事講出來。"
                return f"{honorific}，我是{active_name}。我有聽到你說「{user_message}」，我們可以慢慢聊。"

            system_prompt = self.build_system_prompt(
                profile,
                recent_messages=recent_messages,
                important_memories=important_memories,
                similar_memories=similar_memories,
                active_persona=active_persona,
            )

            history = [
                types.Content(
                    role="user" if msg["role"] == "user" else "model",
                    parts=[types.Part(text=msg["content"])],
                )
                for msg in conversation_history
            ]
            history.append(
                types.Content(role="user", parts=[types.Part(text=user_message)])
            )

            response = client.models.generate_content(
                model=self.model_name,
                contents=history,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.9,
                    max_output_tokens=2000,
                ),
            )
            return response.text

        except Exception as e:
            print(f"LLM 錯誤：{e}")
            return "抱歉，我剛剛沒聽清楚，可以再說一次嗎？"

    # ------------------------------------------------------------------
    # Public: background generation helpers
    # ------------------------------------------------------------------

    def generate_memory_summary(self, events: list, name: str) -> str:
        """Summarise recent events into a caregiver-readable paragraph."""
        client = _get_client()
        if client is None:
            if not events:
                return f"{name} 近期沒有可彙整的對話事件。"
            latest = events[-1]
            return f"{name} 近期主要提到「{latest.get('event', '')}」，情緒狀態為 {latest.get('sentiment', 'neutral')}，建議照護者持續觀察。"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        events_text = "\n".join(
            f"- {e.get('date', '')} {e.get('time', '')}：{e.get('event', '')}（情緒分數：{e.get('emotion_score', 0):.1f}，{e.get('reason', '')}）"
            for e in events
        )
        prompt = f"""你是長照系統的記憶彙整模組。
    請將以下 {name} 的近期對話紀錄，整理成給照護人員參考的摘要。

    彙整時間：{current_time}

    【近期對話紀錄】
    {events_text}

    輸出結構（依實際內容決定是否寫入每項）：
    - 第一句：時間相對關係（今日／日前／本週）+ 整體情緒基調（必寫）
    - 若有安全事件（頭暈、跌倒、胸痛）：優先一句話說明
    - 若情緒有明顯轉折：描述轉折過程，不用平均值帶過
    - 結尾：最重要的一件事或長者說的重要內容

    要求：
    - 第三人稱，自然口語，不列點
    - 只回傳摘要文字，不要標題或其他說明"""

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=500),
        )
        return response.text.strip()

    def update_biography(
        self,
        name: str,
        existing_bio: str,
        important_events: list,
        family_notes: list,
    ) -> str:
        """Merge new evidence into an existing elder biography."""
        client = _get_client()
        if client is None:
            return existing_bio

        events_text = "\n".join(
            f"- {e.get('event', '')}（依據：{e.get('reason', '')}）"
            for e in important_events
        ) if important_events else "無"

        # Coarse dedup: skip notes already verbatim in the bio
        filtered_notes = [
            n for n in family_notes
            if not (existing_bio and n.get("note", "") in existing_bio)
        ]
        family_notes_text = "\n".join(
            f"- {n.get('note', '')}" for n in filtered_notes
        ) if filtered_notes else "無"

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

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=1000),
        )
        return response.text.strip()

    def generate_persona_tone(
        self,
        relation: str,
        name: str,
        language_text: str,
        personality: list,
        habits: list,
    ) -> str:
        """Generate a short speaking-style description for a persona."""
        client = _get_client()
        if client is None:
            traits = "、".join(personality[:2]) if personality else "溫和"
            habit = habits[0] if habits else "自然陪伴"
            return f"像{name}這位{relation}，語氣{traits}，會{habit}。"

        prompt = f"""根據以下資料，生成一段「說話風格描述」供 AI 扮演參考：

- 關係：{relation}
- 名字：{name}
- 語言習慣：{language_text}
- 個性：{', '.join(personality) if personality else '未指定'}
- 說話習慣：{', '.join(habits) if habits else '未指定'}

要求：
- 50字以內
- 描述說話語氣、用詞習慣、互動方式
- 融合關係和個性，自然口語
- 只回傳描述文字，不要標題或說明"""

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=200),
        )
        return response.text.strip()
