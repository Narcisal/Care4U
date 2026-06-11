# Decision Agent

協調所有 agent 的執行順序，是系統的指揮官。

**檔案**：`backend/agents/decision.py`

---

## 依賴關係

| 呼叫誰 | 被誰呼叫 |
|---------|---------|
| `MagicAI.chat()` / `stream_chat()` / `greet()` | `main.py` 的 `/api/chat`、`/api/greet` |
| `ISafe.analyze()` / `record_emergency()` | `main.py` 的 `/api/admin/safety` |
| `VectorMemoryStore` (生平更新) | — |
| `TTSService` (設定引擎) | — |
| `image_gen` / `health_search` (背景任務) | — |

---

## Module-level 全域狀態

| 變數 | 型別 | 用途 |
|------|------|------|
| `_agent_logs` | `deque(maxlen=100)` | 最近 100 筆 agent 操作日誌，admin API 可讀取 |
| `_agent_executor` | `ThreadPoolExecutor(workers=AGENT_EXECUTOR_WORKERS)` | MagicAI / iSafe 平行執行、生平更新的共用 thread pool |
| `_magic_agents` | `dict[str, MagicAI]` | Agent 快取，key 為 `{elder_id}:{session_id}:{persona_id}` |
| `_isafe_agents` | `dict[str, ISafe]` | 同上 |
| `_agents_lock` | `threading.Lock` | 保護上述兩個 dict 的讀寫 |
| `_biography_updates_in_progress` | `set[str]` | 記錄哪些 elder_id 正在更新生平，避免重複排程 |

### Agent 快取 key 格式

```
_agent_key("W001", "default", "persona_1")  →  "W001:default:persona_1"
_agent_key("W001", None, None)              →  "W001:default:profile"
```

同一個 key 的 MagicAI 和 iSafe 會被重用。`clear_agent()` 按 prefix 匹配刪除，會先 flush 對話歷史再移除。

---

## Public API

### `__init__(elder_id, session_id="default", persona_id=None)`

1. 透過 `_get_magic()` / `_get_isafe()` 取得（或建立）agent instance
2. 呼叫 `_setup_persona()` 從 profile 讀取 persona 設定 TTS

**`_setup_persona()` 細節**：
- 從 `VectorMemoryStore.get_profile()` 讀取 personas dict
- 選擇 active persona：`persona_id` 參數 > `profile["active_persona"]` > `"ai"`
- 設定 TTS 引擎和聲音樣本路徑
- **失敗降級**：任何 exception → 使用 edge-tts + 預設 persona `{"name": "AI 助理", "honorific": "爺爺"}`

### `greet() → dict`

委派給 `MagicAI.greet()`。失敗時回傳硬編碼問候語。

回傳 dict：`{message, emotion, elder_id, persona_name}`

### `chat(user_message, speed_emotion="normal") → dict`

非串流對話，完整流程：

```
1. quick_keyword_check(message) == 3?
   └─ YES: record_emergency() → 直接回傳緊急 dict，不呼叫 LLM
2. 決定 use_rag = (quick_keyword_check != 0)
3. ThreadPoolExecutor 平行提交：
   ├─ _run_isafe(message, speed_emotion)  → safety dict
   └─ _run_magic(message, use_rag)        → {"_text": str, "_magic_ms": int}
4. 等待兩者完成（.result()）
5. _patch_last_model_message()：把 iSafe 的 escalation_level 寫回對話歷史
6. escalation_level ≥ 2 → 附加通知文字
7. 每 10 輪 → _schedule_biography_update()
```

**回傳 dict 完整欄位**：

```python
{
    "message": str,           # 回應文字
    "emotion": str,           # "normal" | "happy" | "comfort" | "urgent"
    "is_urgent": bool,
    "sentiment": str,         # "positive" | "negative" | "neutral"
    "trend_alert": str | None,
    "escalation_level": int,  # 0-3
    "elder_id": str,
    "history_length": int,
    "image": None,            # 由 main.py 背景任務填入
    "image_caption": None,
    "health_info": None,      # 由 main.py 背景任務填入
    "persona_name": str,
    "_isafe_ms": int | None,  # debug: iSafe 耗時
    "_magic_ms": int | None,  # debug: MagicAI 耗時
    "_chat_total_ms": int,    # debug: 總耗時
    "_llm_used": bool,        # iSafe 是否呼叫了 LLM
    "_isafe_path": str,       # "safe_keyword" | "llm" | "emergency_keyword" | "llm_error"
}
```

### `stream_chat(user_message, speed_emotion="normal") → Generator[dict]`

SSE 串流版本。yield 兩種 dict：

- `{"type": "chunk", "chunk": str}` — 串流中的每一段文字
- `{"type": "done", ...}` — 最終完整結果（與 `chat()` 回傳格式相同，多一個 `_first_chunk_ms`）

**與 `chat()` 的關鍵差異**：
- iSafe 在 ThreadPoolExecutor 中執行
- MagicAI streaming 在**主執行緒** yield（因為 generator 無法跨 thread）
- MagicAI 串流失敗 → yield fallback 文字 `"抱歉，我剛剛沒聽清楚，可以再說一次嗎？"`
- iSafe 在串流**結束後**才 `.result()` 收集

---

## Internal Methods

### `_run_isafe(message, speed_emotion) → dict`

包裝 `ISafe.analyze()`，加上計時和錯誤降級。失敗回傳：

```python
{"emotion": "normal", "is_urgent": False, "sentiment": "neutral", "_isafe_path": "llm_error"}
```

### `_run_magic(message, use_rag) → dict`

包裝 `MagicAI.chat()`，失敗回傳 `{"_text": "抱歉，我剛剛沒聽清楚..."}`.

### `_patch_last_model_message(escalation_level, sentiment)`

從 `conversation_history` 末尾往前找第一個 `role=="model"` 的 message，注入 `escalation_level` 和 `sentiment`。讓 admin 介面可以直接從對話歷史讀取安全分級。

### `_run_image_gen(message) → (str|None, str|None)`

1. `detect_image_trigger()` 判斷是否包含視覺場景
2. `generate_image()` 生成圖片（base64）
3. 根據 persona 的 relation 生成不同語氣的 caption
4. 失敗回傳 `(None, None)`

### `_run_health_search(message) → dict|None`

1. `detect_health_topic()` 檢查是否包含健康關鍵字
2. `search_health_info()` 透過 Tavily 搜尋
3. 失敗回傳 `None`，不影響對話

### `_schedule_biography_update()`

**去重機制**：`_biography_updates_in_progress` set 確保同一個 elder_id 不會同時有兩個生平更新在跑。

流程：
1. 檢查 elder_id 是否已在更新中
2. 提交 `_update_biography()` 到 thread pool
3. 透過 `future.add_done_callback()` 清理 set

### `_update_biography()`

1. 讀取 profile → 取最近 10 筆 importance ≥ 0.7 的事件 + family notes
2. 呼叫 `LLMService.update_biography()` 生成新生平
3. **品質檢查**：
   - 長度 > 50 字
   - 已有生平時：key facts（長者名字、前職業、persona 名字）必須出現在新生平中
   - 新生平長度 ≥ 舊生平 70%
   - 不通過 → 放棄更新
4. `set_biography(skip_if_manual=True)` — 若照護者手動編輯過，不覆蓋

---

## Module-level Functions

### `flush_agent_conversations()`

Server shutdown 時呼叫（lifespan handler）。遍歷所有 `_magic_agents`，逐一 `flush_conversation()` 到磁碟。

### `clear_agent(elder_id, session_id=None)`

按 prefix 匹配刪除 agent。先 flush 對話歷史再移除。用於 admin 清除對話。

### `get_logs() → list`

回傳 `_agent_logs` deque 的 snapshot，供 admin 介面顯示。

---

## Gotchas

1. **`_lock` 是 `asyncio.Lock`，不是 `threading.Lock`**：但 `chat()` 和 `stream_chat()` 都在 sync context 呼叫，這個 lock 實際上**沒有被使用**。它是早期殘留，目前的併發保護來自 `_agents_lock` 和 thread pool。
2. **`use_rag = quick_keyword_check(message) != 0`**：安全快速路徑的訊息（level 0）不做 RAG，因為 "早安" 不需要搜尋記憶。但 `None`（需 LLM 判定）的訊息會做 RAG，這是刻意設計。
3. **圖片和健康搜尋不在 Decision 內執行**：`_run_image_gen` 和 `_run_health_search` 雖然定義在 Decision class 裡，但是由 `main.py` 在背景 thread 中呼叫，不在 `chat()` / `stream_chat()` 流程內。
4. **生平更新的品質檢查只在已有生平時執行**：首次生平（`existing_bio` 為空）只檢查長度 > 50 字。
