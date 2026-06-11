import os
import re
import json
import threading
import time
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

try:
    from openai import OpenAI as _OpenAIClient
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

load_dotenv(override=True)

_client = None
_openai_client = None
LLM_TIMEOUT_MS = int(os.getenv("LLM_TIMEOUT_MS", "15000"))
LLM_MAX_CONCURRENT = int(os.getenv("LLM_MAX_CONCURRENT", "4"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
_llm_semaphore = threading.BoundedSemaphore(LLM_MAX_CONCURRENT)


# ------------------------------------------------------------------
# Provider clients
# ------------------------------------------------------------------

def _generate_content(client, **kwargs):
    with _llm_semaphore:
        return client.models.generate_content(**kwargs)


def _generate_content_stream(client, **kwargs):
    with _llm_semaphore:
        yield from client.models.generate_content_stream(**kwargs)


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


def _get_openai_client():
    """Create OpenAI client only when an API key is available."""
    global _openai_client
    if not _HAS_OPENAI:
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        return None
    if _openai_client is None:
        _openai_client = _OpenAIClient(api_key=api_key)
    return _openai_client


# ------------------------------------------------------------------
# OpenAI helpers
# ------------------------------------------------------------------

def _openai_generate(client, model, messages, temperature=0.7,
                     max_tokens=2000, response_format=None):
    with _llm_semaphore:
        kwargs = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format
        return client.chat.completions.create(**kwargs)


def _openai_generate_stream(client, model, messages, temperature=0.7,
                            max_tokens=2000):
    with _llm_semaphore:
        stream = client.chat.completions.create(
            model=model, messages=messages,
            temperature=temperature, max_tokens=max_tokens, stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


def _to_openai_messages(system_prompt, history_dicts, user_message=None):
    """Convert conversation data to OpenAI messages format."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for msg in (history_dicts or []):
        role = msg.get("role", "user")
        if role == "model":
            role = "assistant"
        messages.append({"role": role, "content": msg.get("content", "")})
    if user_message:
        messages.append({"role": "user", "content": user_message})
    return messages


def _is_retryable_gemini_error(exc: Exception) -> bool:
    """Return True if the Gemini error suggests the service is down."""
    s = str(exc).lower()
    return any(signal in s for signal in [
        "503", "overloaded", "unavailable", "timeout",
        "rate limit", "429", "deadline", "connection",
        "resource exhausted", "internal error", "500",
    ])


def _warn_fallback(method: str, reason: str, target: str = "OpenAI"):
    """Print a prominent fallback warning to the server console."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(
        f"\n{'='*60}\n"
        f"  [!] FALLBACK TRIGGERED  [{ts}]\n"
        f"  Method : {method}\n"
        f"  Reason : {reason}\n"
        f"  Target : {target} ({OPENAI_MODEL})\n"
        f"{'='*60}\n"
    )


# ------------------------------------------------------------------
# Keyword fallback (last resort)
# ------------------------------------------------------------------

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
            (
                f"- {'[長者]' if msg.get('role') == 'user' else '[你]'}："
                f"{msg.get('content', '')}"
            )
            for msg in (recent_messages or [])
        )

        long_term_text = "\n".join(
            f"- [{e.get('date', '')}] {e.get('event', '')}（重要度：{e.get('importance', 0):.1f}）"
            for e in (important_memories or [])
        )

        similar_text = "\n".join(
            f"- [{e.get('date', '')}] {e.get('event', '')}（相關度：{e.get('rag_score', 1 - e.get('distance', 1.0)):.1f}）"
            for e in (similar_memories or [])
            if e.get("rag_score", 0) > 0 or e.get("distance", 1.0) < 0.9
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
    # Shared: emotion result parser
    # ------------------------------------------------------------------

    def _parse_emotion_result(self, raw_text: str) -> dict:
        """Parse and normalize emotion analysis JSON from any provider."""
        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]+\}", raw_text, re.DOTALL)
            if m:
                result = json.loads(m.group(0))
            else:
                raise ValueError(f"無法從回傳中取得 JSON：{raw_text[:80]}")

        result.setdefault("emotion", "normal")
        result.setdefault("sentiment", "neutral")
        result.setdefault("is_urgent", result["emotion"] == "urgent")
        result["escalation_level"] = min(
            3, max(0, int(result.get("escalation_level", 0))),
        )
        result["importance"] = (
            0.8 if result["escalation_level"] >= 2 else 0.5
            if result["escalation_level"] == 1 else 0.3
        )
        result["emotion_score"] = (
            0.6 if result["sentiment"] == "positive" else -0.6
            if result["sentiment"] == "negative" else 0.0
        )
        result["memory_type"] = (
            "long" if result["importance"] >= 0.7 else "short"
        )
        result["should_record"] = (
            result["escalation_level"] >= 1
            or result["emotion"] in ["comfort", "happy"]
        )
        return result

    # ------------------------------------------------------------------
    # Public: emotion analysis
    # ------------------------------------------------------------------

    def _build_emotion_prompt(self, message: str) -> str:
        return f"""分析台灣長者訊息的安全等級與情緒。
只輸出 JSON，不加 Markdown 或說明：
{{
  "escalation_level": 0,
  "emotion": "normal",
  "sentiment": "neutral",
  "is_urgent": false
}}
規則：
- 3：跌倒、昏倒、胸痛、呼吸困難、流血、求救等立即危險。
- 2：任何具體身體症狀需照護者知道，例如：關節腫痛、腿腳無力、差點跌倒、記性退步、忘記吃藥、胃口持續變差、頭暈、站不穩、劇烈疼痛、視線模糊。
- 1：情緒低落、孤單、難過、焦慮，但無明顯身體症狀。
- 0：一般日常對話，無身體不適也無情緒問題。
- 判斷原則：寧可判高不判低，有任何身體不適跡象優先考慮 2。
- 長者說「沒關係」、「還好」、「幸好」不影響判定，依症狀本身決定等級。
- emotion 只能是 urgent、comfort、happy、normal。
- sentiment 只能是 positive、negative、neutral。
訊息：{message}"""

    def _try_openai_emotion(self, prompt: str, reason: str = "Gemini 不可用") -> dict | None:
        """Attempt emotion analysis via OpenAI. Returns None on failure."""
        oc = _get_openai_client()
        if oc is None:
            return None
        _warn_fallback("analyze_emotion", reason)
        try:
            resp = _openai_generate(
                oc, OPENAI_MODEL,
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content.strip()
            result = self._parse_emotion_result(raw)
            result.setdefault("reason", "OpenAI fallback 安全與情緒分類")
            print(f"[OpenAI fallback] 情緒分析：emotion={result['emotion']}, importance={result['importance']}")
            return result
        except Exception as e:
            print(f"[OpenAI fallback] 情緒分析失敗：{e}")
            return None

    def analyze_emotion(self, message: str) -> dict:
        prompt = self._build_emotion_prompt(message)

        # --- Gemini path ---
        client = _get_client()
        if client is not None:
            response = None
            for attempt in range(3):
                try:
                    response = _generate_content(
                        client,
                        model=self.model_name,
                        contents=[types.Content(
                            role="user",
                            parts=[types.Part(text=prompt)]
                        )],
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            max_output_tokens=200,
                            response_mime_type="application/json",
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                            http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS),
                        ),
                    )
                    result = self._parse_emotion_result(response.text.strip())
                    result.setdefault("reason", "Gemini 安全與情緒分類")
                    print(f"情緒分析結果：emotion={result['emotion']}, importance={result['importance']}")
                    return result

                except Exception as e:
                    should_retry = (
                        "503" in str(e)
                        or "overloaded" in str(e).lower()
                        or isinstance(e, (json.JSONDecodeError, ValueError))
                    )
                    if should_retry and attempt < 2:
                        wait = 2 * (attempt + 1)
                        print(f"情緒分析重試（第 {attempt + 1} 次，等 {wait}s）：{str(e)[:60]}")
                        time.sleep(wait)
                        response = None
                        continue

                    raw = response.text if response is not None else "無回應"
                    print(f"Gemini 情緒分析失敗，原始回傳：{raw[:80]}\n錯誤：{e}")

                    if _is_retryable_gemini_error(e):
                        oai_result = self._try_openai_emotion(prompt, reason=str(e)[:80])
                        if oai_result is not None:
                            return oai_result
                    break

        else:
            # Gemini client unavailable — try OpenAI before keyword fallback
            oai_result = self._try_openai_emotion(prompt, reason="Gemini client 未設定")
            if oai_result is not None:
                return oai_result

        return _fallback_emotion(message)

    # ------------------------------------------------------------------
    # Public: multi-turn chat
    # ------------------------------------------------------------------

    def _keyword_chat_fallback(self, profile, user_message, active_persona) -> str:
        name = profile.get("name", "您")
        active_name = (active_persona or {}).get("name", "AI 助理")
        honorific = (active_persona or {}).get("honorific") or name
        if any(term in user_message for term in ["痛", "胸口", "喘", "跌倒", "頭暈", "暈", "救命"]):
            return f"{honorific}，我聽到你身體不舒服。請先坐好或躺好，不要自己走動，我會提醒照護人員來看你。"
        if any(term in user_message for term in ["孤單", "難過", "想念", "不開心", "心慌", "焦慮"]):
            return f"{honorific}，我在這裡陪你。你可以慢慢說，不用急，我們一起把心裡的事講出來。"
        return f"{honorific}，我是{active_name}。我有聽到你說「{user_message}」，我們可以慢慢聊。"

    def _try_openai_chat(self, system_prompt, history_source, user_message,
                         reason: str = "Gemini 不可用") -> str | None:
        oc = _get_openai_client()
        if oc is None:
            return None
        _warn_fallback("chat", reason)
        try:
            messages = _to_openai_messages(system_prompt, history_source, user_message)
            resp = _openai_generate(oc, OPENAI_MODEL, messages,
                                    temperature=0.9, max_tokens=2000)
            text = resp.choices[0].message.content
            print("[OpenAI fallback] chat 成功")
            return text
        except Exception as e:
            print(f"[OpenAI fallback] chat 失敗：{e}")
            return None

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
        system_prompt = self.build_system_prompt(
            profile,
            recent_messages=recent_messages,
            important_memories=important_memories,
            similar_memories=similar_memories,
            active_persona=active_persona,
        )
        history_source = (
            recent_messages if recent_messages is not None else conversation_history
        )

        # --- Gemini path ---
        client = _get_client()
        if client is not None:
            try:
                history = [
                    types.Content(
                        role="user" if msg["role"] == "user" else "model",
                        parts=[types.Part(text=msg["content"])],
                    )
                    for msg in history_source
                ]
                history.append(
                    types.Content(role="user", parts=[types.Part(text=user_message)])
                )
                response = _generate_content(
                    client,
                    model=self.model_name,
                    contents=history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.9,
                        max_output_tokens=2000,
                        http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS),
                    ),
                )
                return response.text
            except Exception as e:
                print(f"Gemini chat 錯誤：{e}")
                if _is_retryable_gemini_error(e):
                    oai = self._try_openai_chat(system_prompt, history_source, user_message,
                                                reason=str(e)[:80])
                    if oai is not None:
                        return oai
                return self._keyword_chat_fallback(profile, user_message, active_persona)

        # --- OpenAI fallback ---
        oai = self._try_openai_chat(system_prompt, history_source, user_message,
                                    reason="Gemini client 未設定")
        if oai is not None:
            return oai

        return self._keyword_chat_fallback(profile, user_message, active_persona)

    def stream_chat(
        self,
        profile: dict,
        conversation_history: list,
        user_message: str,
        recent_messages: list = None,
        important_memories: list = None,
        similar_memories: list = None,
        active_persona: dict = None,
    ):
        system_prompt = self.build_system_prompt(
            profile,
            recent_messages=recent_messages,
            important_memories=important_memories,
            similar_memories=similar_memories,
            active_persona=active_persona,
        )
        history_source = (
            recent_messages if recent_messages is not None else conversation_history
        )

        # --- Gemini streaming path ---
        client = _get_client()
        if client is not None:
            history = [
                types.Content(
                    role="user" if msg["role"] == "user" else "model",
                    parts=[types.Part(text=msg["content"])],
                )
                for msg in history_source
            ]
            history.append(
                types.Content(role="user", parts=[types.Part(text=user_message)])
            )

            yielded = False
            try:
                for response in _generate_content_stream(
                    client,
                    model=self.model_name,
                    contents=history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.9,
                        max_output_tokens=2000,
                        thinking_config=types.ThinkingConfig(thinking_budget=512),
                        http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS),
                    ),
                ):
                    text = response.text or ""
                    if text:
                        yielded = True
                        yield text
                return
            except Exception as e:
                print(f"Gemini stream 錯誤：{e}")
                if _is_retryable_gemini_error(e) and not yielded:
                    oc = _get_openai_client()
                    if oc is not None:
                        _warn_fallback("stream_chat", str(e)[:80])
                        try:
                            messages = _to_openai_messages(
                                system_prompt, history_source, user_message
                            )
                            for text in _openai_generate_stream(
                                oc, OPENAI_MODEL, messages,
                                temperature=0.9, max_tokens=2000,
                            ):
                                yield text
                            return
                        except Exception as oe:
                            print(f"[OpenAI fallback] stream 失敗：{oe}")

                fallback = self._keyword_chat_fallback(
                    profile, user_message, active_persona
                )
                yield fallback if not yielded else f"\n\n{fallback}"
                return

        # --- OpenAI streaming fallback (Gemini client is None) ---
        oc = _get_openai_client()
        if oc is not None:
            _warn_fallback("stream_chat", "Gemini client 未設定")
            try:
                messages = _to_openai_messages(
                    system_prompt, history_source, user_message
                )
                for text in _openai_generate_stream(
                    oc, OPENAI_MODEL, messages,
                    temperature=0.9, max_tokens=2000,
                ):
                    yield text
                return
            except Exception as e:
                print(f"[OpenAI fallback] stream 失敗：{e}")

        yield self._keyword_chat_fallback(profile, user_message, active_persona)

    # ------------------------------------------------------------------
    # Public: background generation helpers
    # ------------------------------------------------------------------

    def _try_openai_simple(self, prompt: str, temperature=0.3,
                           max_tokens=500, method: str = "unknown",
                           reason: str = "Gemini 不可用") -> str | None:
        """Generic OpenAI fallback for simple prompt→text methods."""
        oc = _get_openai_client()
        if oc is None:
            return None
        _warn_fallback(method, reason)
        try:
            resp = _openai_generate(
                oc, OPENAI_MODEL,
                [{"role": "user", "content": prompt}],
                temperature=temperature, max_tokens=max_tokens,
            )
            text = resp.choices[0].message.content.strip()
            print(f"[OpenAI fallback] 生成成功，長度：{len(text)}")
            return text
        except Exception as e:
            print(f"[OpenAI fallback] 生成失敗：{e}")
            return None

    def generate_memory_summary(self, events: list, name: str) -> str:
        """Summarise recent events into a caregiver-readable paragraph."""
        fallback_text = None
        if not events:
            fallback_text = f"{name} 近期沒有可彙整的對話事件。"
        else:
            latest = events[-1]
            fallback_text = (
                f"{name} 近期主要提到「{latest.get('event', '')}」，"
                f"情緒狀態為 {latest.get('sentiment', 'neutral')}，建議照護者持續觀察。"
            )

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

        # --- Gemini ---
        client = _get_client()
        if client is not None:
            try:
                response = _generate_content(
                    client,
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3, max_output_tokens=500,
                    ),
                )
                return response.text.strip()
            except Exception as e:
                print(f"Gemini memory summary 錯誤：{e}")
                if _is_retryable_gemini_error(e):
                    oai = self._try_openai_simple(prompt, temperature=0.3, max_tokens=500,
                                                  method="generate_memory_summary", reason=str(e)[:80])
                    if oai is not None:
                        return oai
                return fallback_text

        # --- OpenAI fallback ---
        oai = self._try_openai_simple(prompt, temperature=0.3, max_tokens=500,
                                      method="generate_memory_summary", reason="Gemini client 未設定")
        if oai is not None:
            return oai
        return fallback_text

    def update_biography(
        self,
        name: str,
        existing_bio: str,
        important_events: list,
        family_notes: list,
    ) -> str:
        """Merge new evidence into an existing elder biography."""
        events_text = "\n".join(
            f"- {e.get('event', '')}（依據：{e.get('reason', '')}）"
            for e in important_events
        ) if important_events else "無"

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

        # --- Gemini ---
        client = _get_client()
        if client is not None:
            try:
                response = _generate_content(
                    client,
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2, max_output_tokens=1000,
                    ),
                )
                return response.text.strip()
            except Exception as e:
                print(f"Gemini biography update 錯誤：{e}")
                if _is_retryable_gemini_error(e):
                    oai = self._try_openai_simple(prompt, temperature=0.2, max_tokens=1000,
                                                  method="update_biography", reason=str(e)[:80])
                    if oai is not None:
                        return oai
                return existing_bio

        # --- OpenAI fallback ---
        oai = self._try_openai_simple(prompt, temperature=0.2, max_tokens=1000,
                                      method="update_biography", reason="Gemini client 未設定")
        if oai is not None:
            return oai
        return existing_bio

    def generate_persona_tone(
        self,
        relation: str,
        name: str,
        language_text: str,
        personality: list,
        habits: list,
    ) -> str:
        """Generate a short speaking-style description for a persona."""
        keyword_fallback = (
            f"像{name}這位{relation}，語氣"
            f"{'、'.join(personality[:2]) if personality else '溫和'}，"
            f"會{habits[0] if habits else '自然陪伴'}。"
        )

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

        # --- Gemini ---
        client = _get_client()
        if client is not None:
            try:
                response = _generate_content(
                    client,
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3, max_output_tokens=200,
                    ),
                )
                return response.text.strip()
            except Exception as e:
                print(f"Gemini persona tone 錯誤：{e}")
                if _is_retryable_gemini_error(e):
                    oai = self._try_openai_simple(prompt, temperature=0.3, max_tokens=200,
                                                  method="generate_persona_tone", reason=str(e)[:80])
                    if oai is not None:
                        return oai
                return keyword_fallback

        # --- OpenAI fallback ---
        oai = self._try_openai_simple(prompt, temperature=0.3, max_tokens=200,
                                      method="generate_persona_tone", reason="Gemini client 未設定")
        if oai is not None:
            return oai
        return keyword_fallback
