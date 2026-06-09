"""回應時間測試訊息與手動效能評估工具。

量測兩項指標：
- TTFC（首字延遲）：用戶送出訊息到前端出現第一個字的時間，代表「互動即時感」
- Total（完整回應）：完整 AI 回應送達的時間
"""

import argparse
import asyncio
import json
import statistics
import time
from urllib import error, request


MESSAGES_NEW = {
    "W001": [
        "今天想聽首老歌。",
        "昨天去公園找老友下棋，我們下到忘了時間。",
        "我剛才站起來時腰有點痠，坐一下就好多了。",
        "以前和太太騎重型機車去海邊，風吹過來真的很舒服。",
        "兒子最近都在忙電腦的工作，我想問問他哪天有空回來吃飯。",
    ],
    "C001": [
        "陽台的花開了。",
        "小雨上次回來吃了兩碗滷肉，我心情很好。",
        "今天膝蓋有點痠，我先坐著替盆栽剪葉子。",
        "以前當老師時，看到學生終於把字寫好，我總是特別高興。",
        "志明說晚一點會打電話來，我想先準備幾件最近發生的事告訴他。",
    ],
    "L001": [
        "我想聽鳳飛飛。",
        "早市那家的紅豆餅，今天不知道有沒有開。",
        "剛才整理舊布料，又想起以前替大家做衣服的日子。",
        "阿清以前總會陪我聽一片雲，現在聽到還是會想念他。",
        "志宏和雅婷週末要帶孩子回來，我想先縫幾個小袋子送給他們。",
    ],
    "Z001": [
        "今天想下一盤棋。",
        "老王好幾天沒來了，不知道他最近忙什麼。",
        "我以前開自強號最在意準點，一分鐘都不能馬虎。",
        "秀蘭以前會替我準備便當，跑完車回家還有熱湯可以喝。",
        "小宇每次都要我說蒸汽火車的故事，聽完還說以後也想開火車。",
    ],
}

ELDER_NAMES = {
    "W001": "王大明",
    "C001": "陳秀英",
    "L001": "林月琴",
    "Z001": "鄭有福",
}


def test_prompt_dataset_shape():
    assert set(MESSAGES_NEW) == set(ELDER_NAMES)
    assert all(len(messages) == 5 for messages in MESSAGES_NEW.values())
    assert sum(len(messages) for messages in MESSAGES_NEW.values()) == 20
    assert all(
        5 <= len(message) <= 50
        for messages in MESSAGES_NEW.values()
        for message in messages
    )


def post_chat_stream(base_url: str, elder_id: str, message: str) -> tuple[float, float, str]:
    """串流模式發送請求，回傳 (ttfc_s, total_s, reply_text)。"""
    payload = json.dumps(
        {"elder_id": elder_id, "message": message},
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}/api/chat?stream=true",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    ttfc = None
    reply = ""
    with request.urlopen(req, timeout=120) as resp:
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
            if ttfc is None and event.get("chunk"):
                ttfc = time.perf_counter() - started
            if event.get("chunk"):
                reply += event["chunk"]
            if event.get("done"):
                if event.get("message"):
                    reply = event["message"]
                break
    total = time.perf_counter() - started
    return ttfc if ttfc is not None else total, total, reply.strip()


async def run(base_url: str, elder_id: str, show_reply: bool = False):
    elder_ids = list(MESSAGES_NEW) if elder_id == "all" else [elder_id]
    total_list = []

    for current_elder_id in elder_ids:
        print(f"\n{'='*60}")
        print(f"{ELDER_NAMES[current_elder_id]}（{current_elder_id}）")
        print(f"{'='*60}")
        for message in MESSAGES_NEW[current_elder_id]:
            try:
                ttfc, total, reply = await asyncio.to_thread(
                    post_chat_stream,
                    base_url,
                    current_elder_id,
                    message,
                )
            except error.URLError as exc:
                raise SystemExit(f"無法連線到 {base_url}：{exc}") from exc
            total_list.append(total)
            print(f"\n[{total:.2f}s] 長者：{message}")
            print(f"       AI：{reply}")

    def p95(lst):
        s = sorted(lst)
        return s[max(0, round(len(s) * 0.95) - 1)]

    print(f"\n{'='*60}")
    print(f"案例數：{len(total_list)}")
    print(f"回應時間  平均 {statistics.mean(total_list):.2f}s  "
          f"中位數 {statistics.median(total_list):.2f}s  "
          f"P95 {p95(total_list):.2f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--elder",
        choices=[*MESSAGES_NEW, "all"],
        default="all",
        help="指定長者，或以 all 執行全部案例",
    )
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.elder))
