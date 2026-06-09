"""快速對話品質測試：送一則訊息，印出 AI 完整回應。"""

import json
import sys
from urllib import request

BASE_URL = "http://127.0.0.1:8000"

# ── 改這兩行 ──────────────────────────────
ELDER_ID = "W001"
MESSAGE  = "最近常常想起以前和太太騎車的日子。"
# ─────────────────────────────────────────

def chat(elder_id: str, message: str):
    payload = json.dumps(
        {"elder_id": elder_id, "message": message},
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        f"{BASE_URL}/api/chat?stream=true",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print(f"\n[{elder_id}] 長者：{message}")
    print("AI：", end="", flush=True)
    with request.urlopen(req, timeout=60) as resp:
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
            if event.get("chunk"):
                print(event["chunk"], end="", flush=True)
            if event.get("done"):
                level = event.get("escalation_level", 0)
                emotion = event.get("emotion", "")
                print(f"\n\n[iSafe] L{level}  emotion={emotion}")
                break
    print()

if __name__ == "__main__":
    elder = sys.argv[1] if len(sys.argv) > 1 else ELDER_ID
    msg   = sys.argv[2] if len(sys.argv) > 2 else MESSAGE
    chat(elder, msg)
