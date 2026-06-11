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

    def search_cultural_context(
        self,
        birth_year: int | None,
        hometown: str,
        job: str,
    ) -> str:
        """搜尋職業/年代/地方的文化脈絡（不搜本人姓名，避免身份混淆）。
        回傳整合後的脈絡文字；若 Tavily 不可用則回傳空字串。
        """
        if not self.client:
            return ""
        queries = []
        if birth_year:
            decade = (birth_year // 10) * 10
            if job:
                queries.append(f"台灣{decade}年代 {job} 工作生活文化")
            if hometown:
                queries.append(f"{hometown} {decade}年代 地方生活文化")
        if job:
            queries.append(f"台灣 {job} 傳統職業文化 生活")

        seen, snippets = set(), []
        for query in queries[:3]:          # 最多 3 個 query
            try:
                resp = self.client.search(
                    query=query,
                    search_depth="basic",
                    max_results=2,
                    include_answer=True,
                )
            except Exception as e:
                print(f"文化脈絡搜尋失敗：{query} / {e}")
                continue
            answer = (resp.get("answer") or "").strip()
            if answer and answer not in seen:
                seen.add(answer)
                snippets.append(f"[{query}]\n{answer[:300]}")
            for r in resp.get("results", []):
                content = (r.get("content") or "").strip()[:200]
                if content and content not in seen:
                    seen.add(content)
                    snippets.append(content)
                if len(snippets) >= 6:
                    break
            if len(snippets) >= 6:
                break

        return "\n\n".join(snippets)

    def generate_biography(self, name: str, gender: str, job: str,
                            hobbies, personas: dict, health: dict,
                            raw_summary: str = "") -> str:
        """為已存在的長者（有完整 profile）生成傳記草稿。"""
        family_members = [
            {"relation": p.get("relation", ""), "name": p.get("name", "")}
            for pid, p in (personas or {}).items()
            if pid != "ai" and p.get("relation")
        ]
        return self._generate_biography_core(
            name=name,
            gender=gender,
            job=job,
            hobbies=hobbies if isinstance(hobbies, list) else [],
            family_members=family_members,
            birth_year=None,
            hometown="",
            hints="",
            cultural_context=raw_summary,
        ) or self._fallback_biography(name, job, hobbies, personas)

    def generate_biography_for_new_elder(
        self,
        name: str,
        gender: str,
        birth_year: int | None,
        hometown: str,
        job: str,
        hobbies: list,
        family_members: list,   # [{"relation": "兒子", "name": "志明"}, ...]
        hints: str,             # admin 手填的關鍵事件 hint
    ) -> str:
        """為尚未建檔的新長者生成傳記草稿（Tavily 只搜文化脈絡）。"""
        cultural_context = self.search_cultural_context(birth_year, hometown, job)
        result = self._generate_biography_core(
            name=name, gender=gender, job=job, hobbies=hobbies,
            family_members=family_members, birth_year=birth_year,
            hometown=hometown, hints=hints, cultural_context=cultural_context,
        )
        return result or self._fallback_biography(
            name, job, hobbies,
            {m["relation"]: {"relation": m["relation"], "name": m["name"]} for m in family_members},
        )

    def _generate_biography_core(
        self,
        name: str,
        gender: str,
        job: str,
        hobbies: list,
        family_members: list,
        birth_year: int | None,
        hometown: str,
        hints: str,
        cultural_context: str,
    ) -> str:
        try:
            from google import genai
            from google.genai import types

            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return ""
            client = genai.Client(api_key=api_key)

            gender_text = "男性長者" if gender == "male" else "女性長者"
            hobbies_str = "、".join(hobbies) if hobbies else "（未填寫）"
            family_str = "、".join(
                f"{m.get('relation', '')}：{m.get('name', '')}"
                for m in family_members if m.get("relation")
            ) or "（未填寫）"
            birth_str = f"{birth_year} 年生" if birth_year else "（未填寫）"
            hometown_str = hometown or "（未填寫）"

            facts_block = f"""- 姓名：{name}
- 性別：{gender_text}
- 出生年：{birth_str}
- 家鄉：{hometown_str}
- 曾任職業：{job or "（未填寫）"}
- 興趣愛好：{hobbies_str}
- 家人關係：{family_str}
- 關鍵人生事件（admin 填寫）：{hints.strip() if hints and hints.strip() else "（未填寫）"}"""

            cultural_block = cultural_context.strip() if cultural_context and cultural_context.strip() \
                else "（無搜尋結果）"

            prompt = f"""你是一位長照系統的生命故事撰寫人，為 AI 陪伴助理建立長者的生平背景。

═══════════════════════════════
【Layer 1 — 已知事實（唯一可作為個人細節的來源）】
{facts_block}
═══════════════════════════════
【Layer 2 — 時代文化背景（Tavily 搜尋結果，僅供描寫「時代氛圍」用）】
{cultural_block}
═══════════════════════════════

【撰寫規則 — 必須嚴格遵守】
1. 個人事實只能來自 Layer 1，不得自行添加任何：
   具體事件、人名、地點、年份、對話、意外、獎項、疾病
2. Layer 2 只能用來描述「時代氛圍、職業環境、地方文化」，
   絕對不能將其中的具體事件套用到這位長者身上
3. Layer 1 中標記「（未填寫）」的欄位，請完全略過，不做推測
4. 若某段生命歷程不確定，使用模糊表達：
   ✓「在台灣戰後的年代成長」
   ✗「1952 年在台南長大」（年份是推測）
5. 寧可寫短、寫模糊，絕不杜撰

【輸出格式】
- 第三人稱，600 字以內
- 段落：① 成長背景 ② 職業歷程 ③ 家庭關係 ④ 退休與現況
- 只輸出文章本體，不加標題或說明"""

            response = client.models.generate_content(
                model=os.getenv("MAGIC_MODEL", "gemini-2.5-flash"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.15,
                    max_output_tokens=900,
                ),
            )
            biography = response.text.strip()
            if self._is_weak_biography(biography):
                return ""
            print(f"傳記生成完成：{name}（{len(biography)} 字）")
            return biography
        except Exception as e:
            print(f"傳記生成失敗：{e}")
            return ""

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
