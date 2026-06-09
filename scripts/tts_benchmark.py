"""TTS 引擎基準測試：分別量測 edge-tts 和 XTTS 的合成延遲。

前提：後端 (uvicorn) 必須先啟動（edge-tts 測試）。
XTTS 測試另需 XTTS server 運行於 localhost:8082，並提供 --voice-path。

用法：
    # 只跑 edge-tts（預設）
    python scripts/tts_benchmark.py

    # 只跑 XTTS
    python scripts/tts_benchmark.py --engine xtts --voice-path /path/to/voice.wav

    # 兩個都跑
    python scripts/tts_benchmark.py --engine all --voice-path /path/to/voice.wav

    # 指定不同後端 URL
    python scripts/tts_benchmark.py --base-url http://192.168.1.10:8000
"""

import argparse
import json
import os
import statistics
import time
from urllib import error, request as urllib_request

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
XTTS_URL_DEFAULT = os.getenv("XTTS_URL", "http://localhost:8082")
ELDER_ID = "W001"   # 發測試請求用的長者 ID（目前設定 edge engine）

# XTTS 聲音樣本預設路徑（Care4U 專題目錄旁的 xtts 資料夾）
_XTTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "0511", "xtts"
)
VOICE_PATH_DEFAULT = os.path.normpath(os.path.join(_XTTS_DIR, "ref.wav"))

# 代表性 AI 回應句子（短/中/長句各 5 筆，共 15 筆，涵蓋實際系統輸出範圍）
SAMPLES = [
    # 短句（~15–25 字）
    "好，我陪你聽，你想聽哪一首？",
    "膝蓋痠要注意，先坐著休息一下。",
    "花開了一定很漂亮，你平常很細心在照顧。",
    "老王一定還是會來找你下棋的，別擔心。",
    "你說得很有道理，以前的事情你記得真清楚。",
    # 中句（~30–45 字）
    "嗯，那段騎車去海邊的日子真的很美好，風吹過來的感覺，聽你說就覺得很舒服。",
    "腰不舒服要多休息，別硬撐，有沒有需要我幫你拿個熱敷袋？",
    "想聽鳳飛飛啊，好，我陪你一起聽，這首歌總是特別讓人放鬆。",
    "小雨上次回來吃了兩碗滷肉，你心情一定很好，那種被需要的感覺很溫暖。",
    "以前當老師，看著學生把字寫好的那一刻，那種成就感是很難被取代的。",
    # 長句（~50–70 字）
    "爺爺，你說以前開自強號最在意準點，這種對自己工作負責任的態度真的很讓人敬佩。秀蘭煮的便當想必也是一種溫暖的記憶，每次跑完車回來有熱湯可以喝，那種感覺很踏實。",
    "奶奶，花開了一定很漂亮，你每天細心照顧，它們也感受得到你的愛。陽台上有生命在成長，這件事本身就很美好，你覺得呢？",
    "林月琴，你說的那段替鄉親做衣服的歲月，真的很有意義。每一件衣服都是親手縫製，每個人穿上去的時候一定也感受得到你的用心。",
    "王大明，你和太太騎車去海邊的那段時光，光是聽你描述就能感覺到風吹過來的舒服。那種兩個人一起出去走走的自在，是很珍貴的回憶。",
    "鄭有福，你說二仁溪以前的魚很多，現在不知道還有沒有。那條溪陪著你長大，很多故事都在那裡。有機會你可以再跟我說說以前釣魚的事嗎？",
]


# ── edge-tts：透過後端 /api/elder/tts ──────────────────────────────────────

def _call_elder_tts(base_url: str, text: str) -> tuple[float, int]:
    """呼叫後端 TTS API，回傳 (elapsed_s, audio_size_bytes)，失敗回傳 (None, 0)。"""
    payload = json.dumps(
        {"text": text, "emotion": "normal", "elder_id": ELDER_ID},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib_request.Request(
        f"{base_url.rstrip('/')}/api/elder/tts",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib_request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return time.perf_counter() - t0, len(data)
    except error.URLError as exc:
        print(f"    [ERROR] {exc}")
        return None, 0


def benchmark_edge(base_url: str) -> list[float]:
    timings = []
    for i, text in enumerate(SAMPLES, 1):
        elapsed, size = _call_elder_tts(base_url, text)
        if elapsed is not None:
            print(f"  [{i}] {elapsed:.2f}s  {size//1024}KB  {text[:28]}…")
            timings.append(elapsed)
        else:
            print(f"  [{i}] FAIL  {text[:28]}…")
    return timings


# ── XTTS：直接打 XTTS server ───────────────────────────────────────────────

def _call_xtts(xtts_url: str, text: str, voice_path: str) -> tuple[float, int]:
    payload = json.dumps(
        {"text": text, "voice_path": voice_path, "language": "zh-cn", "speed": 1.0},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib_request.Request(
        f"{xtts_url.rstrip('/')}/v1/audio/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib_request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return time.perf_counter() - t0, len(data)
    except error.URLError as exc:
        print(f"    [ERROR] {exc}")
        return None, 0


def benchmark_xtts(xtts_url: str, voice_path: str) -> list[float]:
    timings = []
    for i, text in enumerate(SAMPLES, 1):
        elapsed, size = _call_xtts(xtts_url, text, voice_path)
        if elapsed is not None:
            print(f"  [{i}] {elapsed:.2f}s  {size//1024}KB  {text[:28]}…")
            timings.append(elapsed)
        else:
            print(f"  [{i}] FAIL  {text[:28]}…")
    return timings


# ── 統計輸出 ────────────────────────────────────────────────────────────────

def print_stats(name: str, timings: list[float]):
    if not timings:
        print(f"\n{name}：無有效數據")
        return
    s = sorted(timings)
    p95 = s[max(0, round(len(s) * 0.95) - 1)]
    print(f"\n── {name} 結果（{len(timings)} 筆）──────────────────────")
    print(f"  平均   {statistics.mean(timings):.2f}s")
    print(f"  中位數 {statistics.median(timings):.2f}s")
    print(f"  P95    {p95:.2f}s")
    print(f"  最快   {min(timings):.2f}s  最慢 {max(timings):.2f}s")


# ── 主程式 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TTS 引擎合成延遲基準測試")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT,
                        help="後端 URL（edge-tts 測試用）")
    parser.add_argument("--xtts-url", default=XTTS_URL_DEFAULT,
                        help="XTTS server URL（預設 http://localhost:8082）")
    parser.add_argument("--voice-path", default=VOICE_PATH_DEFAULT,
                        help=f"XTTS 聲音樣本路徑（預設 {VOICE_PATH_DEFAULT}）")
    parser.add_argument(
        "--engine",
        choices=["edge", "xtts", "all"],
        default="edge",
        help="edge=雲端 edge-tts（預設），xtts=本地 XTTS，all=兩個都跑",
    )
    args = parser.parse_args()

    run_edge = args.engine in ("edge", "all")
    run_xtts = args.engine in ("xtts", "all")

    edge_timings = []
    xtts_timings = []

    if run_edge:
        print(f"\n=== edge-tts（雲端合成，透過後端 API）===")
        edge_timings = benchmark_edge(args.base_url)
        print_stats("edge-tts", edge_timings)

    if run_xtts:
        print(f"\n=== XTTS（本地語音複製，直接打 XTTS server）===")
        if not args.voice_path or not os.path.exists(args.voice_path):
            print(f"  ⚠  找不到聲音樣本：{args.voice_path}")
            print("     請先確認 0511/xtts/ref.wav 存在，或用 --voice-path 指定路徑")
        else:
            print(f"  聲音樣本：{args.voice_path}")
            print(f"  XTTS URL：{args.xtts_url}")
            xtts_timings = benchmark_xtts(args.xtts_url, args.voice_path)
            print_stats("XTTS", xtts_timings)

    # 海報數字摘要
    AI_RESPONSE_S = 4.4   # test_response_time.py 量測平均值
    if edge_timings or xtts_timings:
        print("\n══ 海報數字摘要 ══════════════════════════════════")
        if edge_timings:
            avg_e = statistics.mean(edge_timings)
            print(f"  edge-tts  合成延遲：{avg_e:.2f}s")
            print(f"  edge-tts  端對端（AI+TTS）：{AI_RESPONSE_S + avg_e:.1f}s")
        if xtts_timings:
            avg_x = statistics.mean(xtts_timings)
            print(f"  XTTS      合成延遲：{avg_x:.2f}s")
            print(f"  XTTS      端對端（AI+TTS）：{AI_RESPONSE_S + avg_x:.1f}s")
        print(f"\n  ※ 長者聽到第一個字 = AI 回應時間 {AI_RESPONSE_S}s + TTS 合成時間")


if __name__ == "__main__":
    main()
