"""端對端延遲測試：串流 TTS vs 舊版全文 TTS。

模擬前端行為：
  舊版：等 AI 完整回應 → 送整段文字做 TTS → 播放
  新版：收到每個句子立刻送 TTS（並行）→ AI done 後播放

量測三個時間點（全部從送出訊息開始計算）：
  T_ai    ：AI 完整回應到達
  T_old   ：T_ai + 整段文字 TTS 合成完成（舊版體感）
  T_new   ：第一個句子 TTS 合成完成（新版體感，TTS 與 AI 生成並行）

用法：
    python scripts/test_streaming_tts.py              # 全部長者
    python scripts/test_streaming_tts.py --elder W001 # 指定長者
    python scripts/test_streaming_tts.py --base-url http://127.0.0.1:8000
"""

import argparse
import json
import re
import statistics
import threading
import time
from urllib import error, request as urllib_request

BASE_URL = "http://127.0.0.1:8000"

MESSAGES = {
    "W001": [
        "今天想聽首老歌。",
        "昨天去公園找老友下棋，我們下到忘了時間。",
        "以前和太太騎重型機車去海邊，風吹過來真的很舒服。",
        "兒子最近都在忙電腦的工作，不知道哪天有空回來吃飯。",
        "腰的舊傷今天又痠起來了，坐一下就好多了。",
    ],
    "C001": [
        "陽台的花開了。",
        "小雨上次回來吃了兩碗滷肉，我心情很好。",
        "今天膝蓋有點痠，我先坐著替盆栽剪葉子。",
        "志明說晚一點會打電話來，我想先準備幾件事告訴他。",
        "以前當老師時，看到學生終於把字寫好，特別高興。",
    ],
}

ELDER_NAMES = {"W001": "王大明", "C001": "陳秀英"}

SENTENCE_RE = re.compile(r"[^。！？]*[。！？]")


def extract_first_sentence(text: str) -> str | None:
    """從文字中抽出第一個完整句子（以 。！？ 結尾）。"""
    m = SENTENCE_RE.search(text)
    return m.group(0).strip() if m else None


def tts_request(base_url: str, elder_id: str, text: str) -> float:
    """送 TTS 請求，回傳合成時間（秒）。失敗回傳 None。"""
    payload = json.dumps(
        {"text": text, "emotion": "normal", "elder_id": elder_id},
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
            resp.read()
        return time.perf_counter() - t0
    except error.URLError:
        return None


def measure_one(base_url: str, elder_id: str, message: str) -> dict:
    """
    回傳：
      t_ai         : AI 完整回應時間
      t_first_sent : 第一個完整句子出現的時間
      t_tts_full   : 整段 TTS 合成時間（舊版）
      t_tts_first  : 第一句 TTS 合成時間（新版，從第一句出現時開始計）
      reply        : AI 回應文字
      first_sent   : 第一個句子文字
    """
    payload = json.dumps(
        {"elder_id": elder_id, "message": message},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib_request.Request(
        f"{base_url.rstrip('/')}/api/chat?stream=true",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t_start = time.perf_counter()
    t_first_sent = None
    first_sent = None
    first_tts_result = {}  # filled by background thread
    reply = ""
    accumulated = ""

    def fire_first_sentence_tts(sentence: str):
        """第一句一出現就在背景送 TTS，記錄合成時間。"""
        tts_dur = tts_request(base_url, elder_id, sentence)
        if tts_dur is not None:
            first_tts_result["t_tts_first"] = tts_dur

    tts_thread = None

    with urllib_request.urlopen(req, timeout=120) as resp:
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue

            chunk = event.get("chunk", "")
            if chunk:
                reply += chunk
                accumulated += chunk
                # 第一個句子出現時立刻開 TTS 背景請求
                if t_first_sent is None:
                    sentence = extract_first_sentence(accumulated)
                    if sentence:
                        t_first_sent = time.perf_counter() - t_start
                        first_sent = sentence
                        tts_thread = threading.Thread(
                            target=fire_first_sentence_tts,
                            args=(sentence,),
                            daemon=True,
                        )
                        tts_thread.start()

            if event.get("done"):
                if event.get("message"):
                    reply = event["message"]
                break

    t_ai = time.perf_counter() - t_start

    # 等第一句 TTS 結束（應該早就好了）
    if tts_thread:
        tts_thread.join(timeout=60)

    # 舊版：AI done 後再送整段 TTS
    tts_full_dur = tts_request(base_url, elder_id, reply)

    return {
        "t_ai": t_ai,
        "t_first_sent": t_first_sent,
        "t_tts_full": tts_full_dur,
        "t_tts_first": first_tts_result.get("t_tts_first"),
        "reply": reply.strip(),
        "first_sent": first_sent or "",
    }


def p95(lst):
    s = sorted(lst)
    return s[max(0, round(len(s) * 0.95) - 1)]


async_placeholder = None  # not needed; synchronous


def run(base_url: str, elder_id: str):
    elder_ids = list(MESSAGES) if elder_id == "all" else [elder_id]

    old_list, new_list = [], []

    for eid in elder_ids:
        name = ELDER_NAMES.get(eid, eid)
        print(f"\n{'='*64}")
        print(f"{name}（{eid}）")
        print(f"{'='*64}")

        for msg in MESSAGES[eid]:
            print(f"\n  長者：{msg}")
            r = measure_one(base_url, eid, msg)

            t_old = r["t_ai"] + (r["t_tts_full"] or 0)

            # 新版體感：
            #   第一句 TTS 在 t_first_sent 時並行啟動，耗時 t_tts_first
            #   前端在 AI done（t_ai）後才播放
            #   若 TTS 比 AI 先完成 → 等待為 0，t_new = t_ai
            #   若 TTS 還沒好      → t_new = t_first_sent + t_tts_first
            if r["t_first_sent"] is not None and r.get("t_tts_first") is not None:
                tts_ready = r["t_first_sent"] + r["t_tts_first"]
                t_new = max(r["t_ai"], tts_ready)
            else:
                t_new = t_old  # 無法切句，fallback

            saved = t_old - t_new
            tts_f = r.get("t_tts_first")
            tts_f_str = f"{tts_f:.2f}s" if tts_f is not None else "N/A"
            print(f"  AI 回應：{r['t_ai']:.2f}s  |  全文TTS：{r['t_tts_full']:.2f}s  |  舊版體感：{t_old:.2f}s")
            print(f"  第一句（在 {r['t_first_sent']:.2f}s 出現）：「{r['first_sent']}」")
            print(f"  第一句TTS：{tts_f_str}  →  新版體感：{t_new:.2f}s  （省 {saved:.2f}s）")

            old_list.append(t_old)
            new_list.append(t_new)

    if old_list:
        print(f"\n{'='*64}")
        print(f"{'':4}{'舊版（AI+全文TTS）':>18}  {'新版（串流TTS）':>16}  {'節省':>8}")
        print(f"{'平均':4}{statistics.mean(old_list):>17.2f}s  "
              f"{statistics.mean(new_list):>15.2f}s  "
              f"{statistics.mean(old_list)-statistics.mean(new_list):>7.2f}s")
        print(f"{'中位數':4}{statistics.median(old_list):>16.2f}s  "
              f"{statistics.median(new_list):>15.2f}s  "
              f"{statistics.median(old_list)-statistics.median(new_list):>7.2f}s")
        print(f"{'P95':4}{p95(old_list):>17.2f}s  "
              f"{p95(new_list):>15.2f}s  "
              f"{p95(old_list)-p95(new_list):>7.2f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument(
        "--elder", choices=[*MESSAGES, "all"], default="all",
        help="指定長者，或 all 跑全部"
    )
    args = parser.parse_args()
    run(args.base_url, args.elder)
