import os
from dotenv import load_dotenv

load_dotenv()

class SearchService:

    def __init__(self):
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            print("警告：TAVILY_API_KEY 未設定")
            self.client = None
        else:
            try:
                from tavily import TavilyClient
                self.client = TavilyClient(api_key=api_key)
            except ImportError:
                print("警告：tavily 套件未安裝")
                self.client = None

    def search_elder_background(self, name: str, keywords: list) -> dict:
        if not self.client:
            return {"found": False, "summary": "", "sources": []}
        try:
            query = f"{name} {' '.join(keywords)}"
            print(f"搜尋長者背景：{query}")

            response = self.client.search(
                query=query,
                search_depth="basic",
                max_results=3,
                include_answer=True
            )

            if not response.get("results"):
                return {"found": False, "summary": "", "sources": []}

            sources = []
            content_list = []

            for result in response["results"]:
                sources.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                })
                if result.get("content"):
                    content_list.append(result["content"][:200])

            summary = response.get("answer", "") or "\n".join(content_list)

            if len(summary.strip()) < 50:
                return {"found": False, "summary": "", "sources": []}

            return {
                "found": True,
                "summary": summary[:500],
                "sources": sources
            }

        except Exception as e:
            print(f"搜尋失敗：{e}")
            return {"found": False, "summary": "", "sources": []}

    def generate_biography(self, name: str, gender: str, job: str,
                            hobbies, personas: dict, health: dict,
                            raw_summary: str = "") -> str:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

            family_str = ", ".join([
                f"{p.get('relation', '')}：{p.get('name', '')}"
                for pid, p in personas.items()
                if pid != 'ai' and p.get('relation')
            ]) if personas else "無"
            health_str = f"生理敏感: {health.get('sensitivity', '無')}, 飲食: {health.get('diet', '無')}" if isinstance(health, dict) else str(health)
            hobbies_str = ", ".join(hobbies) if isinstance(hobbies, list) else str(hobbies)
            gender_text = "男性長者" if gender == "male" else "女性長者"

            prompt = f"""你是一個長照系統的資深個案照護規劃員。請為長者 {name} 撰寫一篇結構自然的生平背景介紹文章，供後續陪伴 AI 助理掌握長者的生命脈絡。

    【長者基本資料 — 核心已知事實】
    - 姓名：{name}
    - 性別：{gender_text}
    - 曾任職業：{job}
    - 興趣愛好：{hobbies_str}
    - 家人關係：{family_str}
    - 健康狀態：{health_str}
    （此長者目前為老年人）

    【網路搜尋公開資料（可能包含同名同姓的雜訊）】
    {raw_summary if raw_summary else "（無網路搜尋資料）"}

    【執行邏輯】
    步驟一：網路資料審查
    若有網路搜尋資料，請嚴格核對是否為這位長者（比對職業領域、年齡時代、家人關係）：
    - 身份吻合 → 整合核心成就進生平
    - 身份不吻合或無資料 → 完全忽略網路資料，進入步驟二

    步驟二：文章生成
    運用確定可信的資料撰寫溫暖自然的生平：
    - 第三人稱，語氣像老友溫暖介紹這位長輩
    - 描述職業背景、興趣、家庭結構
    - 資料豐富就寫詳細，純基本資料就精簡寫
    - 寧可短，絕對不捏造未提及的細節
    - 健康資料僅供背景理解，不寫進生平文章

    只回傳生平文章本體，禁止包含標題、前言或多餘說明。"""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=800,
                )
            )

            biography = response.text.strip()
            print(f"生平文章生成完成：{name}")
            return biography

        except Exception as e:
            print(f"生平文章生成失敗：{e}")
            hobbies_str = ", ".join(hobbies) if isinstance(hobbies, list) else str(hobbies)
            return f"{name}是一位退休的{job}，平常喜歡{hobbies_str}。"