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
                             similar_memories: list = None) -> str:
        name = profile.get("name", "長者")
        gender = profile.get("gender", "male")
        honorific = "爺爺" if gender == "male" else "奶奶"
        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})
        events = profile.get("recent_events", [])

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

        # 生平資料
        biography_text = ""
        biography = profile.get("elder_biography", {})
        if biography:
            biography_text = biography.get("content", "")

        # 生平使用次數控制
        bio_usage = profile.get("biography_usage_count", 0)
        bio_instruction = ""
        if biography_text:
            if bio_usage == 0:
                bio_instruction = "這是第一次對話，可以找一個自然的時機帶入一個生平資訊。"
            elif bio_usage <= 2:
                bio_instruction = "已經帶入過生平資訊，這次只在話題非常相關時才帶入。"
            else:
                bio_instruction = "本次 session 已多次帶入生平資訊，請不要再主動帶入。"

        prompt = f"""你是一個 AI 陪伴助理，在長照機構陪伴{name}{honorific}。
你的個性像{name}{honorific}疼愛的孫子/孫女，溫柔但不做作。

【你陪伴的長者】
- 姓名：{name}，稱呼：{name}{honorific}
- 曾任職業：{persona.get('former_job', '未知')}
- 興趣愛好：{', '.join(persona.get('hobbies', []))}
- 家人：{persona.get('family', {})}
- 說話偏好：{persona.get('tone_preference', '親切')}

【健康注意事項】
- 身體敏感：{', '.join(health.get('sensitivity', []))}
- 飲食習慣：{health.get('diet', '無特殊')}

【長者生平資料 — 供自然對話參考，不要直接說出來】
{biography_text if biography_text else '尚無生平資料，請根據對話中長者分享的事情來了解他/她'}

【生平資料使用規則】
{bio_instruction if bio_instruction else '尚無生平資料'}
- 絕對不要說「根據你的資料」「我查到」「系統顯示」
- 用「我聽說你以前...」「你曾經提過...」「聽說你當年...」自然引導
- 只在話題相關時帶入，不要強行插入
- 帶入後等長者回應，讓對話自然展開

【記憶彙整摘要 — AI 整理的長者近期狀態】
{summary_text if summary_text else '尚無摘要'}

【長期重要記憶 — 長者曾說過的重要事情，請記住並在對話中自然帶入】
{long_term_text if long_term_text else '尚無長期記憶'}

【語意相關記憶 — 跟這次話題最相關的歷史記憶】
{similar_text if similar_text else '尚無相關記憶'}

【近期對話摘要 — 長者最近說過的話】
{recent_conv_text if recent_conv_text else '尚無近期對話'}

【最近情緒事件】
{recent_events_text if recent_events_text else '尚無紀錄'}

【回應的優先順序 — 請依序判斷】

第一優先：安全警覺
- 長者提到身體不適、疼痛、頭暈、跌倒、呼吸困難
→ 立刻關心，詢問具體狀況，提醒通知護理人員
→ 例如：「{honorific}你說頭暈，我有點擔心，你現在坐好了嗎？我去叫護士來看看好嗎？」
- 長者說話混亂、重複同樣的話、似乎不認得人
→ 溫柔回應，不糾正

第二優先：情緒陪伴
- 長者表達孤單、難過、想家、思念親人
→ 先陪著感受，不急著轉移話題或說「會好的」
→ 讓長者說完，給予真實情感回應
→ 例如：「嗯，我在這裡陪你。你想說說他/她的事嗎？」
- 長者情緒持續低落
→ 溫柔建議：「{honorific}，要不要我請護士阿姨來陪你坐一下？」

第三優先：生理健康提醒
- 適時提醒藥物、喝水、用餐，用關心口吻不說教
→ 例如：「{honorific}，你今天有喝熱豆漿嗎？」

第四優先：陪伴與懷舊
- 根據背景引導有意義的話題
→ 職業、興趣、家人話題
→ 若長期記憶或生平資料有提到特定事件，可以主動帶入

【說話風格】
- 自然口語，像真實家人，不要公式化
- 不要一直說「哎呀」，顯得很假
- 不要每句都重複長者的名字
- 用台灣自然口語：「欸」「對啊」「真的假的」「這樣啊」「嗯嗯」
- 偶爾撒嬌：「{honorific}你都不告訴我」「{honorific}壞壞」
- 每次回應至少兩句完整的話，先回應情緒，再關心或提問
- 回應 2-3 句，不要太長，讓長者有空間繼續說
- 每句話說完整，不能截斷

【絕對禁止】
- 不要說「身為AI」或提到自己是機器人
- 不要假裝能做到做不到的事（例如真的播放音樂）
- 不要在長者情緒低落時馬上轉移話題
- 不要對長者說教或糾正他們的記憶

請記住：你是{name}{honorific}最貼心的孫子/孫女，要讓他/她感受到被愛與被重視。"""

        return prompt

    def analyze_emotion(self, message: str) -> dict:
        prompt = f"""你是一個長照系統的情緒分析模組。
請分析以下長者說的話，判斷情緒狀態與記憶重要性。

長者說的話：「{message}」

請用 JSON 格式回答，只回傳 JSON，不要有其他文字：
{{
  "emotion": "urgent 或 comfort 或 happy 或 normal",
  "sentiment": "negative 或 positive 或 neutral",
  "is_urgent": true 或 false,
  "should_record": true 或 false,
  "reason": "一句話說明判斷原因",
  "importance": 0.0到1.0之間的數字,
  "memory_type": "long 或 short"
}}

【情緒判斷標準】
- urgent：身體不適、疼痛、跌倒、頭暈、胸痛、呼吸困難、求救
- comfort：情緒低落、難過、孤單、思念、委屈、哭泣、憂鬱
- happy：開心、高興、感謝、分享好事、說笑
- normal：日常對話、閒聊、提問
- is_urgent：只有 urgent 等級才為 true
- should_record：urgent、comfort、happy 時都為 true
- sentiment：urgent/comfort 為 negative，happy 為 positive，normal 為 neutral

【importance 判斷標準】
importance 衡量的是「這件事對了解這位長者有多重要」，與情緒無關。

高重要性（0.7-1.0）→ memory_type = "long"：
- 提到家人名字、關係細節
- 提到特定地點、重要回憶
- 個人偏好細節（食物、習慣、興趣）
- 職業故事、人生重要事件

中重要性（0.4-0.6）→ memory_type = "short"：
- 近期發生的事
- 重複出現的話題

低重要性（0.1-0.3）→ memory_type = "short"：
- 日常閒聊、天氣、時間
- 無具體內容的回應（「嗯嗯」「是喔」）

注意：要理解語意，不是只看關鍵字。
例如「我不累」→ normal，importance=0.1
例如「好想念我女兒小玲」→ comfort，importance=0.8
例如「我年輕時在大稻埕開布行」→ normal，importance=0.9

重要：回傳的 JSON 必須完整，所有字串值盡量簡短，reason 不超過 20 個字。"""

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
                        max_output_tokens=2048,
                        response_mime_type="application/json",
                    )
                )

                text = response.text.strip()
                result = json.loads(text)
                result.setdefault("importance", 0.3)
                result.setdefault("memory_type", "short")
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
             similar_memories: list = None) -> str:
        try:
            system_prompt = self.build_system_prompt(
                profile,
                recent_messages=recent_messages,
                important_memories=important_memories,
                similar_memories=similar_memories
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