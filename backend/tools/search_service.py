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

            return {
                "found": True,
                "summary": summary[:500],
                "sources": sources
            }

        except Exception as e:
            print(f"搜尋失敗：{e}")
            return {"found": False, "summary": "", "sources": []}

    def generate_biography(self, raw_summary: str,
                            name: str, profile: dict) -> str:
        if not raw_summary:
            return ""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

            persona = profile.get("persona", {})
            job = persona.get("former_job", "")
            hobbies = ", ".join(persona.get("hobbies", []))

            prompt = f"""你是一個長照系統，正在為 AI 陪伴助理準備關於長者的背景資料。

長者基本資料：
- 姓名：{name}
- 曾任職業：{job}
- 興趣：{hobbies}

網路搜尋到的公開資料：
{raw_summary}

請整理成一段自然的生平介紹文章（150字以內），格式如下：
- 用第三人稱
- 包含職業、成就、人生重要事件
- 語氣像朋友介紹朋友，自然不做作
- 只寫有根據的事實，不要捏造
- 如果搜尋結果跟這位長者完全無關，只回傳「無相關公開資料」

只回傳文章內容，不要標題或說明。"""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=300,
                )
            )
            result = response.text.strip()
            print(f"生平文章生成完成：{result[:50]}...")
            return result

        except Exception as e:
            print(f"生平文章生成失敗：{e}")
            return ""

    def filter_relevant_info(self, raw_summary: str,
                              name: str, llm_service) -> str:
        if not raw_summary:
            return ""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            prompt = f"""以下是關於「{name}」的網路搜尋結果：

{raw_summary}

請從中擷取對長照陪伴有用的資訊，例如：
- 職業背景、人生成就
- 重要作品、著作
- 曾任職的機構或職位
- 其他有助於個人化對話的事實

如果找不到相關資訊，回傳「無相關公開資料」。
只回傳整理後的資訊，不超過 150 字。"""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=300,
                )
            )
            return response.text.strip()

        except Exception as e:
            print(f"LLM 過濾失敗：{e}")
            return raw_summary[:150]