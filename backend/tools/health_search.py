import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

HEALTH_KEYWORDS = {
    "復健": ["復健動作", "物理治療", "復健運動"],
    "用藥": ["藥物說明", "服藥方式", "藥物副作用"],
    "飲食": ["長者飲食", "銀髮族營養", "老人飲食建議"],
    "睡眠": ["改善睡眠", "老人失眠", "睡眠品質"],
    "血壓": ["高血壓控制", "血壓管理", "量血壓"],
    "糖尿病": ["糖尿病飲食", "血糖控制", "糖尿病照護"],
    "跌倒": ["防跌運動", "跌倒預防", "平衡訓練"],
    "失智": ["失智症照護", "認知訓練", "腦部健康"],
}

TRIGGER_KEYWORDS = [
    "怎麼做", "如何", "教我", "示範", "復健",
    "運動", "藥", "飲食", "吃什麼", "血壓",
    "血糖", "跌倒", "失智", "睡不好", "睡眠"
]

class HealthSearchService:

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

    def detect_health_topic(self, message: str) -> str | None:
        if not any(kw in message for kw in TRIGGER_KEYWORDS):
            return None
        for topic, keywords in HEALTH_KEYWORDS.items():
            if topic in message or any(kw in message for kw in keywords):
                return topic
        if any(kw in message for kw in ["怎麼做", "如何", "教我", "示範"]):
            return "general"
        return None

    def search_health_info(self, message: str, topic: str) -> dict | None:
        if not self.client:
            return None
        try:
            if topic in HEALTH_KEYWORDS:
                query = f"台灣 {HEALTH_KEYWORDS[topic][0]} 衛教 長者"
            else:
                query = f"台灣 {message[:20]} 衛教資訊 長者"

            print(f"搜尋健康衛教：{query}")

            response = self.client.search(
                query=query,
                search_depth="basic",
                max_results=3,
                include_answer=True
            )

            if not response.get("results"):
                return None

            best = response["results"][0]
            summary = response.get("answer") or best.get("content", "")[:200]

            return {
                "title": best.get("title", "健康衛教資訊"),
                "summary": summary[:300],
                "url": best.get("url", ""),
                "source": urlparse(best.get("url", "")).netloc if best.get("url") else ""
            }

        except Exception as e:
            print(f"健康搜尋失敗：{e}")
            return None