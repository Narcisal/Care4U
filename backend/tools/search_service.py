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

    def build_search_queries(self, profile: dict, extra_keywords: list | None = None) -> list[str]:
        name = (profile.get("name") or "").strip()
        persona = profile.get("persona", {}) or {}
        family_notes = profile.get("family_notes", []) or []
        if not name:
            return []

        seeds = []
        job = (persona.get("former_job") or "").strip()
        if job:
            seeds.append(job)
        for hobby in persona.get("hobbies", []) or []:
            if hobby:
                seeds.append(str(hobby).strip())
        for note in family_notes[-5:]:
            text = (note.get("note") or "").strip()
            for token in text.replace("，", " ").replace("、", " ").split():
                if 2 <= len(token) <= 20 and token not in seeds:
                    seeds.append(token)
        for keyword in extra_keywords or []:
            keyword = str(keyword).strip()
            if keyword and keyword not in seeds:
                seeds.append(keyword)

        queries = [name]
        for seed in seeds[:6]:
            queries.append(f"{name} {seed}")
        return list(dict.fromkeys(queries))

    def search_background_candidates(self, profile: dict, extra_keywords: list | None = None) -> dict:
        queries = self.build_search_queries(profile, extra_keywords)
        if not self.client:
            return {
                "queries": queries,
                "candidates": [],
                "message": "TAVILY_API_KEY 未設定或 tavily 套件未安裝，已產生搜尋線索但未能查詢公開資料。",
            }

        seen_urls = set()
        candidates = []
        for query in queries:
            try:
                response = self.client.search(
                    query=query,
                    search_depth="basic",
                    max_results=3,
                    include_answer=True,
                )
            except Exception as e:
                print(f"候選來源搜尋失敗：{query} / {e}")
                continue

            for result in response.get("results", []):
                url = result.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                content = (result.get("content") or "").strip()
                candidates.append({
                    "id": f"source_{len(candidates) + 1}",
                    "query": query,
                    "title": result.get("title", "未命名來源"),
                    "url": url,
                    "summary": content[:350],
                    "confidence": self._rough_match_label(profile, query, content),
                })
                if len(candidates) >= 8:
                    break
            if len(candidates) >= 8:
                break

        return {
            "queries": queries,
            "candidates": candidates,
            "message": "已找到候選公開資料。" if candidates else "沒有找到可用的候選公開資料。",
        }

    def _rough_match_label(self, profile: dict, query: str, content: str) -> str:
        text = f"{query} {content}"
        score = 0
        name = profile.get("name", "")
        job = (profile.get("persona", {}) or {}).get("former_job", "")
        if name and name in text:
            score += 1
        if job and job in text:
            score += 1
        if score >= 2:
            return "可能相符"
        if score == 1:
            return "需要確認"
        return "不確定"

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
            if self._is_weak_biography(biography):
                biography = self._fallback_biography(name, job, hobbies, personas)
            print(f"生平文章生成完成：{name}")
            return biography

        except Exception as e:
            print(f"生平文章生成失敗：{e}")
            return self._fallback_biography(name, job, hobbies, personas)

    def _is_weak_biography(self, biography: str) -> bool:
        if not biography or len(biography.strip()) < 80:
            return True
        return biography.strip().endswith(("，", "、", "；", "：", ":", ",", ";"))

    def _fallback_biography(self, name: str, job: str, hobbies, personas: dict) -> str:
        hobbies_list = hobbies if isinstance(hobbies, list) else [str(hobbies)] if hobbies else []
        hobbies_str = "、".join([h for h in hobbies_list if h]) or "日常生活中的熟悉事物"
        family = [
            f"{p.get('relation', '')}{p.get('name', '')}".strip()
            for pid, p in (personas or {}).items()
            if pid != "ai" and p.get("relation") and p.get("name")
        ]
        family_str = "，家人包含" + "、".join(family) if family else ""
        job_text = job if job and job != "未知" else "自己的工作崗位"
        return (
            f"{name}是一位重視生活情感與家庭連結的長者，過去曾在{job_text}累積人生經驗。"
            f"這位長者平時熟悉並喜歡{hobbies_str}{family_str}。"
            "這些背景可作為陪伴對話時的自然話題，讓回應更貼近長者的生命經驗與日常習慣。"
        )
