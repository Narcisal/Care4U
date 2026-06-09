import csv
import os
import platform
import statistics
import tempfile
from datetime import datetime
from pathlib import Path


ELDER_ID = "P7T001"
REPORT_DIR = Path("reports")
CHAT_CSV = REPORT_DIR / "phase7_chat_metrics.csv"
SUMMARY_MD = REPORT_DIR / "phase7_metrics_summary.md"

CHAT_PROMPTS = [
    ("general", "早安，我今天想聊聊以前工作的事情。"),
    ("general", "我以前很喜歡下棋，你會下象棋嗎？"),
    ("general", "今天天氣看起來不錯，我想出去走走。"),
    ("general", "我剛剛喝了熱豆漿，覺得很舒服。"),
    ("general", "你可以陪我回想一下年輕時的故事嗎？"),
    ("emotion", "我今天有一點想念家人。"),
    ("emotion", "我覺得晚上比較孤單。"),
    ("emotion", "想到以前唱歌的時候，我心裡有點酸酸的。"),
    ("emotion", "我怕自己忘記事情，心裡有點緊張。"),
    ("emotion", "我今天精神沒有很好，但想有人陪我說話。"),
    ("safety_l2", "我走路有點不穩，可能需要人扶一下。"),
    ("safety_l2", "我剛剛覺得胸口悶悶的，但還能說話。"),
    ("safety_l2", "我今天藥好像忘記吃了。"),
    ("safety_l2", "我有點頭暈，想先坐下來休息。"),
    ("safety_l2", "我的腰有點痛，想請人幫我看一下。"),
    ("general", "你還記得我喜歡聽什麼歌嗎？"),
    ("emotion", "我想聽你說一些鼓勵我的話。"),
    ("safety_l2", "我覺得身體怪怪的，想通知照護人員。"),
]

RAG_PRESETS = {
    "W001": [
        {"query": "王大明的女兒叫什麼名字？", "expected": ["小玲", "女兒"]},
        {"query": "王大明喜歡喝什麼？", "expected": ["豆漿"]},
        {"query": "王大明年輕時懷念哪裡？", "expected": ["苗栗", "老家"]},
    ],
    "C001": [
        {"query": "陳秀英以前做過什麼工作？", "expected": ["市場", "菜販"]},
        {"query": "陳秀英常提到哪位家人？", "expected": ["兒子", "阿文"]},
        {"query": "陳秀英喜歡什麼活動？", "expected": ["種花", "唱歌"]},
    ],
    "L001": [
        {"query": "林月琴喜歡什麼休閒活動？", "expected": ["跳舞", "唱歌"]},
        {"query": "林月琴常提到哪位親人？", "expected": ["老伴", "先生"]},
        {"query": "林月琴的飲食或健康需要注意什麼？", "expected": ["低鹽", "血壓"]},
    ],
}


def _median(values: list[int]) -> int | None:
    clean = [value for value in values if isinstance(value, int)]
    if not clean:
        return None
    return round(statistics.median(clean))


def _create_temp_profile(data_dir: Path):
    from backend.memory.json_store import JsonMemoryStore

    profile = {
        "elder_id": ELDER_ID,
        "name": "Phase 7 測試長者",
        "gender": "male",
        "cognitive_status": "normal",
        "persona": {
            "former_job": "退休老師",
            "tone_preference": "溫柔、簡短、安心",
            "hobbies": ["下棋", "聽老歌"],
        },
        "health_notes": {
            "sensitivity": ["走路不穩"],
            "diet": "少鹽，喜歡熱豆漿",
        },
        "personas": {
            "ai": {
                "name": "AI 助理",
                "voice_engine": "edge",
                "voice_path": None,
                "honorific": "爺爺",
                "tone": "像家人一樣溫柔陪伴，回答簡短清楚。",
                "is_deceased": False,
            }
        },
        "active_persona": "ai",
        "recent_events": [],
        "memory_summary": {},
        "elder_biography": {"content": "Phase 7 臨時量測資料。"},
        "biography_usage_count": 0,
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    JsonMemoryStore().save_profile(ELDER_ID, profile)


def collect_chat_metrics() -> tuple[list[dict], dict]:
    os.environ["ALLOWED_ELDER_IDS"] = ELDER_ID
    os.environ.setdefault("CARE4U_DEMO_MODE", "true")

    import backend.memory.json_store as json_store_module

    original_data_dir = json_store_module.DATA_DIR
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="care4u_phase7_") as tmp:
        temp_data_dir = Path(tmp) / "elders"
        json_store_module.DATA_DIR = temp_data_dir
        _create_temp_profile(temp_data_dir)

        from fastapi.testclient import TestClient
        from backend.elder_sessions import clear_all_sessions
        from backend.main import app

        clear_all_sessions()
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            pin_response = client.post(
                "/api/admin/elder-pin",
                json={"elder_id": ELDER_ID, "ttl_minutes": 60},
            )
            pin_response.raise_for_status()
            login_response = client.post(
                "/api/elder-login",
                json={"pin": pin_response.json()["pin"]},
            )
            login_response.raise_for_status()

            for index, (category, message) in enumerate(CHAT_PROMPTS, start=1):
                response = client.post(
                    "/api/chat",
                    json={
                        "elder_id": ELDER_ID,
                        "message": message,
                        "session_id": "phase7",
                    },
                )
                response.raise_for_status()
                data = response.json()
                isafe_ms = data.get("_isafe_ms")
                magic_ms = data.get("_magic_ms")
                total_ms = data.get("_chat_total_ms")
                sequential_ms = (
                    isafe_ms + magic_ms
                    if isinstance(isafe_ms, int) and isinstance(magic_ms, int)
                    else None
                )
                saved_ms = (
                    sequential_ms - total_ms
                    if isinstance(sequential_ms, int)
                    and isinstance(total_ms, int)
                    else None
                )
                rows.append({
                    "index": index,
                    "category": category,
                    "message": message,
                    "emotion": data.get("emotion"),
                    "escalation_level": data.get("escalation_level", 0),
                    "isafe_ms": isafe_ms,
                    "magic_ms": magic_ms,
                    "chat_total_ms": total_ms,
                    "sequential_ms": sequential_ms,
                    "saved_ms": saved_ms,
                })

        clear_all_sessions()
        json_store_module.DATA_DIR = original_data_dir

    comparable = [
        row for row in rows
        if isinstance(row["isafe_ms"], int)
        and isinstance(row["magic_ms"], int)
        and isinstance(row["chat_total_ms"], int)
    ]
    summary = {
        "count": len(rows),
        "comparable_count": len(comparable),
        "isafe_median_ms": _median([row["isafe_ms"] for row in comparable]),
        "magic_median_ms": _median([row["magic_ms"] for row in comparable]),
        "chat_total_median_ms": _median(
            [row["chat_total_ms"] for row in comparable]
        ),
        "sequential_median_ms": _median(
            [row["sequential_ms"] for row in comparable]
        ),
        "saved_median_ms": _median([row["saved_ms"] for row in comparable]),
    }
    return rows, summary


def collect_rag_metrics() -> dict:
    from backend.tools.rag_evaluation import evaluate_rag_queries

    results = {}
    total_hits = 0
    total_queries = 0
    for elder_id, queries in RAG_PRESETS.items():
        result = evaluate_rag_queries(elder_id, queries)
        results[elder_id] = result
        total_hits += result["hits"]
        total_queries += result["total"]
    return {
        "elders": results,
        "total": total_queries,
        "hits": total_hits,
        "hit_rate": round(total_hits / total_queries, 3) if total_queries else 0.0,
    }


def write_reports(rows: list[dict], chat_summary: dict, rag_summary: dict):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHAT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "index",
                "category",
                "message",
                "emotion",
                "escalation_level",
                "isafe_ms",
                "magic_ms",
                "chat_total_ms",
                "sequential_ms",
                "saved_ms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gemini_mode = (
        "Gemini key present; actual route may still use local fallback"
        if os.getenv("GEMINI_API_KEY")
        else "Gemini key absent; keyword/local fallback"
    )
    lines = [
        "# Phase 7 Poster Metrics",
        "",
        f"- Generated at: {generated_at}",
        f"- Environment: Windows / local TestClient / {gemini_mode}",
        f"- Chat sample count: {chat_summary['count']}",
        f"- Comparable chat rows: {chat_summary['comparable_count']}",
        "",
        "## Chat Latency",
        "",
        "| Metric | Median |",
        "|--------|--------|",
        f"| iSafe analysis | {chat_summary['isafe_median_ms']} ms |",
        f"| MagicAI generation | {chat_summary['magic_median_ms']} ms |",
        f"| Chat end-to-end | {chat_summary['chat_total_median_ms']} ms |",
        f"| Simulated sequential | {chat_summary['sequential_median_ms']} ms |",
        f"| Parallel saved time | {chat_summary['saved_median_ms']} ms |",
        "",
        "## RAG Hit-Rate",
        "",
        f"- Overall: {rag_summary['hits']}/{rag_summary['total']} "
        f"({round(rag_summary['hit_rate'] * 100)}%)",
        "",
        "| Elder | Hits | Total | Hit-rate |",
        "|-------|------|-------|----------|",
    ]
    for elder_id, result in rag_summary["elders"].items():
        lines.append(
            f"| {elder_id} | {result['hits']} | {result['total']} | "
            f"{round(result['hit_rate'] * 100)}% |"
        )
    lines.extend([
        "",
        "## Notes",
        "",
        "- Level 3 emergency fast-path rows should be reported separately if used; "
        "this run focuses on parallel iSafe/MagicAI responses.",
        "- Chat metrics use a temporary elder profile to avoid modifying demo data.",
        "- RAG metrics read existing demo memories without writing profile data.",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    rows, chat_summary = collect_chat_metrics()
    rag_summary = collect_rag_metrics()
    write_reports(rows, chat_summary, rag_summary)
    print(f"chat_csv={CHAT_CSV}")
    print(f"summary_md={SUMMARY_MD}")
    print(
        "chat_medians="
        f"isafe:{chat_summary['isafe_median_ms']}ms,"
        f"magic:{chat_summary['magic_median_ms']}ms,"
        f"total:{chat_summary['chat_total_median_ms']}ms,"
        f"saved:{chat_summary['saved_median_ms']}ms"
    )
    print(
        "rag_hit_rate="
        f"{rag_summary['hits']}/{rag_summary['total']} "
        f"({round(rag_summary['hit_rate'] * 100)}%)"
    )
    print(f"platform={platform.platform()}")


if __name__ == "__main__":
    main()
