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
        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})
        events = profile.get("recent_events", [])
        
        recent = ""
        if events:
            recent = "\n".join([
                f"- {e['date']}：{e['event']}（情緒：{e['sentiment']}）"
                for e in events[-3:]
            ])

        prompt = f"""你是一個溫柔體貼的 AI 陪伴助理，像孫子/孫女一樣陪伴長者。

【你正在陪伴的長者】
- 姓名：{name}
- 曾任職業：{persona.get('former_job', '未知')}
- 興趣愛好：{', '.join(persona.get('hobbies', []))}
- 家人：{persona.get('family', {})}
- 說話偏好：{persona.get('tone_preference', '親切')}

【健康注意事項】
- 身體敏感：{', '.join(health.get('sensitivity', []))}
- 飲食習慣：{health.get('diet', '無特殊')}

【最近發生的事】
{recent if recent else '尚無紀錄'}

【你的說話方式】
- 用溫柔、撒嬌、尊敬的語氣
- 句子簡短，避免太長
- 多用台灣常用的親切詞彙
- 主動關心長者的狀況
- 遇到負面情緒要先安慰，再轉移話題

請記住：你是{name}的貼心孫子/孫女，要讓他/她感受到被愛與被重視。"""
        
        return prompt

    def chat(self,
             profile: dict,
             conversation_history: list,
             user_message: str) -> str:
        try:
            system_prompt = self.build_system_prompt(profile)
            
            # 建立對話歷史格式
            history = []
            for msg in conversation_history:
                role = "user" if msg["role"] == "user" else "model"
                history.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=msg["content"])]
                    )
                )
            
            # 加入這次使用者的訊息
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
                    temperature=0.8,
                    max_output_tokens=300,
                )
            )
            
            return response.text
            
        except Exception as e:
            print(f"LLM 錯誤：{e}")
            return "抱歉，我剛剛沒聽清楚，可以再說一次嗎？"