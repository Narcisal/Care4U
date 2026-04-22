import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

class LLMService:
    
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name
    
    def build_system_prompt(self, profile: dict) -> str:
        name = profile.get("name", "長者")
        gender = profile.get("gender", "male")
        honorific = "爺爺" if gender == "male" else "奶奶"
        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})
        events = profile.get("recent_events", [])
        
        recent = ""
        if events:
            recent = "\n".join([
                f"- {e['date']}：{e['event']}（情緒：{e['sentiment']}）"
                for e in events[-3:]
            ])

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

    【最近發生的事】
    {recent if recent else '尚無紀錄'}

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
    → 職業：數學、教書的故事
    → 興趣：鄧麗君的歌、象棋
    → 家人：小玲、小寶的近況

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
        """
        用 LLM 判斷長者訊息的情緒狀態
        回傳格式：
        {
            "emotion": "urgent" | "comfort" | "happy" | "normal",
            "sentiment": "negative" | "positive" | "neutral",
            "is_urgent": bool,
            "should_record": bool,
            "reason": str
        }
        """
        prompt = f"""你是一個長照系統的情緒分析模組。
請分析以下長者說的話，判斷情緒狀態。

長者說的話：「{message}」

請用 JSON 格式回答，只回傳 JSON，不要有其他文字：
{{
  "emotion": "urgent 或 comfort 或 happy 或 normal",
  "sentiment": "negative 或 positive 或 neutral",
  "is_urgent": true 或 false,
  "should_record": true 或 false,
  "reason": "一句話說明判斷原因"
}}

判斷標準：
- urgent：身體不適、疼痛、跌倒、頭暈、胸痛、呼吸困難、求救
- comfort：情緒低落、難過、孤單、思念、委屈、哭泣、憂鬱
- happy：開心、高興、感謝、分享好事、說笑
- normal：日常對話、閒聊、提問

- is_urgent：只有 urgent 等級才為 true
- should_record：urgent 或 comfort 時為 true，需要照護人員注意
- sentiment：urgent/comfort 為 negative，happy 為 positive，normal 為 neutral

注意：要理解語意，不是只看關鍵字。
例如「我不累」應判定為 normal，不是 comfort。
例如「腿有點痠」應判定為 comfort，不是 urgent。
例如「好想念我女兒」應判定為 comfort。"""

        try:
            response = client.models.generate_content(
                model=self.model_name,
                contents=[types.Content(
                    role="user",
                    parts=[types.Part(text=prompt)]
                )],
                config=types.GenerateContentConfig(
                    temperature=0.1,  # 情緒分析要穩定，temperature 調低
                    max_output_tokens=200,
                )
            )

            import json
            text = response.text.strip()
            # 清除可能的 markdown code block
            text = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(text)
            return result

        except Exception as e:
            print(f"情緒分析失敗，使用預設值：{e}")
            # 失敗時回傳安全的預設值
            return {
                "emotion": "normal",
                "sentiment": "neutral",
                "is_urgent": False,
                "should_record": False,
                "reason": "分析失敗，使用預設值"
            }

    def chat(self,
             profile: dict,
             conversation_history: list,
             user_message: str) -> str:
        try:
            system_prompt = self.build_system_prompt(profile)
            
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