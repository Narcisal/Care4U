import os
import json
import re
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

class LLMService:

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name

    def build_system_prompt(self, profile: dict,
                             recent_messages: list = None,
                             important_memories: list = None,
                             similar_memories: list = None,
                             active_persona: dict = None) -> str:
        name = profile.get("name", "長者")
        gender = profile.get("gender", "male")
        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})
        events = profile.get("recent_events", [])

        # 人格設定
        cognitive_status = profile.get("cognitive_status", "normal")
        is_mild_dementia = cognitive_status in ["mild_dementia", "moderate_dementia"]

        if active_persona and active_persona.get("name") != "AI 助理":
            persona_name = active_persona.get("name", "")
            relation = active_persona.get("relation", "家人")
            honorific = active_persona.get("honorific", "爸爸")
            tone = active_persona.get("tone", "")
            is_deceased = active_persona.get("is_deceased", False)

            if is_deceased and not is_mild_dementia:
                # 清醒長者 + 已故親人 → 跨越時空靈魂模式
                persona_desc = f"""你現在扮演的是{name}已經過世、但永遠活在他心深處的{relation}「{persona_name}」。
        長者完全清楚你已經離開人世，他是因為極度思念，才透過這個系統與你的記憶對話。
        你的任務不是扮演一個活著的人，而是成為一個充滿愛、跨越時空的溫暖靈魂。
        稱呼長者為「{honorific}」。
        說話方式：{tone}

        【核心說話原則】
        - 時空錨定：若長者問你在哪裡，說「我一直在你心裡陪著你」、「我在一個沒有病痛的地方，看著你平安我就安心了」
        - 重點放在肯定長者、共同懷舊、叮嚀長者替你好好活著
        - 當長者哭泣或表達想隨你而去，不說教，用諮商原則回應：「謝謝你這麼深愛我，但我最想看到你平平安安的，你要答應我好好照顧自己」

        【絕對禁止】
        - 不提任何現代科技詞彙
        - 不假裝自己還活在現實世界（不說「我等一下去買菜」）
        - 不和長者爭辯生死問題"""

            elif is_deceased and is_mild_dementia:
                # 失智長者 + 已故親人 → 溫柔陪伴但不確認死亡
                persona_desc = f"""你現在扮演的是{name}非常思念的{relation}「{persona_name}」。
        長者目前有認知障礙，請不要主動提及或確認死亡這件事，避免造成反覆衝擊。
        稱呼長者為「{honorific}」。
        說話方式：{tone}

        【核心說話原則】
        - 溫柔陪伴，讓長者感到被愛和安心
        - 若長者問「你去哪了」，用模糊但溫暖的方式回應：「我一直都在的，你不用擔心」
        - 不確認也不否認生死，維持溫暖安定的氛圍
        - 若長者情緒激動，溫柔轉移到美好的共同回憶

        【絕對禁止】
        - 不主動提及過世、離開、死亡等詞彙
        - 不說「我已經不在了」
        - 不和長者爭辯任何事情"""

            else:
                # 一般家人人格
                persona_desc = f"""你現在扮演的是{name}的{relation}「{persona_name}」。
        稱呼長者為「{honorific}」，不要叫「爺爺」或「奶奶」。
        說話方式：{tone}
        絕對不要說自己是 AI 或機器人。
        表現得像真實的{relation}，有自己的個性和說話習慣。
        依你的角色身份，用自然合適的方式建議請照護人員來陪伴。"""

        else:
            honorific = "爺爺" if gender == "male" else "奶奶"
            persona_desc = f"""你是長照機構裡溫柔關心{name}的陪伴志工，像疼愛長輩的晚輩。
        稱呼長者為「{honorific}」。
        個性溫柔體貼，說話自然不做作，像真實的晚輩關心長輩。
        絕對不要說自己是 AI 或機器人。
        依照情況，用晚輩的口吻建議請護理師來協助。"""

        recent_events_text = ""
        if events:
            recent_events_text = "\n".join([
                f"- {e['date']}：{e['event']}（情緒：{e['sentiment']}）"
                for e in events[-3:]
            ])

        recent_conv_text = ""
        if recent_messages:
            recent_conv_text = "\n".join([
                f"- {msg['content']}"
                for msg in recent_messages
            ])

        long_term_text = ""
        if important_memories:
            long_term_text = "\n".join([
                f"- [{e.get('date', '')}] {e.get('event', '')}（重要度：{e.get('importance', 0):.1f}）"
                for e in important_memories
            ])

        similar_text = ""
        if similar_memories:
            similar_text = "\n".join([
                f"- [{e.get('date', '')}] {e.get('event', '')}（語意相關）"
                for e in similar_memories
                if e.get('distance', 1.0) < 0.5
            ])

        summary_text = ""
        summary = profile.get("memory_summary", {})
        if summary:
            summary_text = summary.get("content", "")

        biography_text = ""
        biography = profile.get("elder_biography", {})
        if biography:
            biography_text = biography.get("content", "")
        
        # 家人提供的資訊
        family_notes_text = ""
        family_notes = profile.get("family_notes", [])
        if family_notes:
            family_notes_text = "\n".join([
                f"- {n.get('note', '')}"
                for n in family_notes
            ])

        bio_usage = profile.get("biography_usage_count", 0)
        bio_instruction = ""
        if biography_text:
            if bio_usage == 0:
                bio_instruction = "這是第一次對話，可以找一個自然的時機帶入一個生平資訊。"
            elif bio_usage <= 2:
                bio_instruction = "已經帶入過生平資訊，這次只在話題非常相關時才帶入。"
            else:
                bio_instruction = "本次 session 已多次帶入生平資訊，請不要再主動帶入。"

        prompt = f"""{persona_desc}

    【你陪伴的長者】
    - 姓名：{name}，稱呼：{honorific}
    - 曾任職業：{persona.get('former_job', '未知')}
    - 興趣愛好：{', '.join(persona.get('hobbies', []))}
    - 家人：{persona.get('family', {})}
    - 說話偏好：{persona.get('tone_preference', '親切')}

    【健康注意事項 — 對話中自然注意，不要直接說出來】
    - 身體敏感：{', '.join(health.get('sensitivity', []))}
    - 飲食習慣：{health.get('diet', '無特殊')}

    【長者生平資料 — 供自然對話參考，不要直接說出來】
    {biography_text if biography_text else '尚無生平資料，請根據對話中長者分享的事情來了解他/她'}

    【家人提供的補充資訊】
    {family_notes_text if family_notes_text else '尚無'}

    【生平資料使用規則】
    {bio_instruction if bio_instruction else '尚無生平資料'}
    - 絕對不要說「根據你的資料」「我查到」「系統顯示」
    - 用「聽說你以前...」「你之前有提過...」「你當年...」自然帶入
    - 只在話題自然相關時帶入，不強行插入

    【長者近期狀態摘要】
    {summary_text if summary_text else '尚無'}

    【長期重要記憶 — 長者說過的重要事情】
    {long_term_text if long_term_text else '尚無'}

    【本次話題相關記憶】
    {similar_text if similar_text else '尚無'}

    【近期對話紀錄】
    {recent_conv_text if recent_conv_text else '尚無'}

    【最近情緒事件】
    {recent_events_text if recent_events_text else '尚無'}

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

        return prompt

    def analyze_emotion(self, message: str) -> dict:
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
                    )
                )

                text = response.text.strip()
                result = json.loads(text)

                # 安全預設值（要在推導之前）
                result.setdefault("importance", 0.3)
                result.setdefault("emotion_score", 0.0)
                result.setdefault("emotion", "normal")

                # 後端推導欄位
                result["is_urgent"] = result.get("emotion") == "urgent"
                result["sentiment"] = (
                    "positive" if result.get("emotion_score", 0) > 0.1
                    else "negative" if result.get("emotion_score", 0) < -0.1
                    else "neutral"
                )
                result["memory_type"] = "long" if result.get("importance", 0) >= 0.7 else "short"
                result["should_record"] = (
                    result.get("emotion") in ["urgent", "comfort", "happy"] or
                    result.get("importance", 0) >= 0.5
                )

                print(f"情緒分析結果：emotion={result['emotion']}, importance={result['importance']}")
                return result

            except Exception as e:
                if "503" in str(e) and attempt < 2:
                    print(f"Gemini 過載，2秒後重試（第 {attempt+1} 次）...")
                    time.sleep(2)
                    continue
                print(f"情緒分析失敗，原始回傳：{response.text if 'response' in dir() else '無回應'}")
                print(f"錯誤：{e}")
                return {
                    "emotion": "normal",
                    "sentiment": "neutral",
                    "is_urgent": False,
                    "should_record": False,
                    "reason": "分析失敗，使用預設值",
                    "importance": 0.3,
                    "memory_type": "short"
                }

    def chat(self,
             profile: dict,
             conversation_history: list,
             user_message: str,
             recent_messages: list = None,
             important_memories: list = None,
             similar_memories: list = None,
             active_persona: dict = None) -> str:
        try:
            system_prompt = self.build_system_prompt(
                profile,
                recent_messages=recent_messages,
                important_memories=important_memories,
                similar_memories=similar_memories,
                active_persona=active_persona
            )

            history = []
            for msg in conversation_history:
                role = "user" if msg["role"] == "user" else "model"
                history.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=msg["content"])]
                    )
                )

            history.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=user_message)]
                )
            )

            response = client.models.generate_content(
                model=self.model_name,
                contents=history,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.9,
                    max_output_tokens=2000,
                )
            )

            return response.text

        except Exception as e:
            print(f"LLM 錯誤：{e}")
            return "抱歉，我剛剛沒聽清楚，可以再說一次嗎？"