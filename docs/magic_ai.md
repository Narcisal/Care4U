# MagicAI Agent

管理單一 session 的對話上下文，負責產生自然回應。

**檔案**：`backend/agents/magic_ai.py`

---

## 依賴關係

| 呼叫誰 | 被誰呼叫 |
|---------|---------|
| `LLMService.chat()` / `stream_chat()` | `Decision._run_magic()` / `Decision.stream_chat()` |
| `LLMService.generate_memory_summary()` | 自身 `_summarize_memories()`（每 10 次對話） |
| `EmbeddingService.embed()` | RAG 查詢時 |
| `VectorMemoryStore.*` | 記憶讀寫 |

---

## Instance 狀態

| 屬性 | 型別 | 生命週期 | 說明 |
|------|------|---------|------|
| `elder_id` | `str` | 永久 | 長者 ID |
| `persona_id` | `str \| None` | 永久 | 建構時傳入 |
| `_persona_key` | `str` | 永久 | `persona_id or "ai"`，用於對話歷史的檔案名 |
| `llm` | `LLMService` | 永久 | 使用 `MAGIC_MODEL` 環境變數（預設 `gemini-2.5-flash`） |
| `memory` | `VectorMemoryStore` | 永久 | |
| `embedding` | `EmbeddingService` | 永久 | |
| `profile` | `dict` | 永久 | **初始化時讀取一次，之後不更新**（注意：不反映運行中的 profile 變更） |
| `_chat_count` | `int` | session | 本次 session 的對話次數，驅動定期任務 |
| `conversation_history` | `list[dict]` | session | in-memory 對話歷史，啟動時從磁碟恢復 |

---

## Public API

### `greet() → str`

根據時間段（早安/午安/晚安）+ persona 稱謂生成問候語。

- AI persona → `"{name}{爺爺/奶奶}，{時段}！"`
- 自訂 persona → `"{honorific}，{時段}！"`

問候語會被 append 到 `conversation_history`（role="model"）。

### `chat(user_message, use_rag=True) → str`

非串流對話生成。

**RAG 記憶檢索流程**：

```
use_rag == True?
├─ embed(user_message) → query_embedding
│   ├─ 有向量 → search_similar_memories(query_embedding, limit=5)
│   └─ 無向量（embed 回傳 None）→ search_similar_memories([], query_text=message)
│       └─ 走 JSON 關鍵字 fallback
└─ use_rag == False → skip，similar_memories = []
```

**重要記憶查詢**：

```python
# 查 12 筆 importance ≥ 0.7，排除安全/趨勢標籤，取前 8 筆
important_memories = [
    m for m in get_important_memories(threshold=0.7, limit=12)
    if not {"安全警報", "趨勢警報"}.intersection(m.get("topic_tags") or [])
][:8]
```

排除原因：安全警報會讓對話 prompt 變得沉重，影響回應的自然度。

**送給 LLM 的 context 組合**：

| 參數 | 來源 | 數量 |
|------|------|------|
| `profile` | `self.profile` | 1 份完整 profile dict |
| `conversation_history` | `self.conversation_history` | 全部（LLM 內部只取最後幾輪） |
| `user_message` | 參數 | 當前使用者訊息 |
| `recent_messages` | `conversation_history[-4:]` | 最近 4 則對話 |
| `important_memories` | 上方查詢結果 | 最多 8 筆 |
| `similar_memories` | RAG 查詢結果 | 最多 5 筆 |
| `active_persona` | `_get_active_persona()` | 當前人格設定 |

### `stream_chat(user_message, use_rag=True) → Generator[str]`

與 `chat()` 相同的 context 準備，但呼叫 `LLMService.stream_chat()`，逐 chunk yield。

串流結束後呼叫 `_record_response()` 寫入歷史（同步）。

### `clear_memory()`

清空 in-memory `conversation_history` 並刪除磁碟上的對話檔案。

### `flush_conversation() → bool`

立即將 `conversation_history` 寫入磁碟。server shutdown 時由 `flush_agent_conversations()` 呼叫。

### `get_history() → list`

回傳 `conversation_history` 的引用（不是 copy）。

---

## Internal Methods

### `_record_response(user_message, response, rag_hits)`

每次對話後執行：

1. 將 user 和 model message append 到 `conversation_history`
2. **歷史上限**：`len > 50` → 截斷為最後 50 則
3. `_chat_count += 1`
4. **每 5 次**：
   - `_reset_biography_usage()` 重設生平使用計數
   - `save_conversation()` 到磁碟
5. **每 10 次**：`_summarize_memories()` 做記憶彙整

### `_summarize_memories()`

1. 取最近 10 筆事件
2. 少於 5 筆 → 跳過
3. 呼叫 `LLMService.generate_memory_summary()` 生成摘要
4. 寫入 `profile["memory_summary"]`

### `_get_active_persona() → dict`

Persona 選擇優先順序：
1. `self.persona_id`（建構時指定）
2. `profile["active_persona"]`
3. `"ai"` 預設

### `_reset_biography_usage()`

重設 `profile["biography_usage_count"]` 為 0。用於控制 LLM system prompt 中生平資料的引用頻率。

---

## 對話歷史格式

每則 message 的 dict：

```python
# user message
{"role": "user", "content": "今天膝蓋好痛", "date": "2025-01-15", "time": "14:30:00"}

# model message
{"role": "model", "content": "爺爺，先坐好...", "date": "2025-01-15", "time": "14:30:02",
 "_rag_hits": 3,               # MagicAI 自己加的
 "escalation_level": 2,        # Decision._patch_last_model_message() 注入
 "sentiment": "negative"}      # 同上
```

---

## Gotchas

1. **`profile` 在初始化時快照，不會自動更新**：如果 admin 在運行中修改了 profile，MagicAI 不會看到。需要 `clear_agent()` 重建 instance。
2. **`conversation_history` 是引用**：`Decision` 透過 `magic.get_history()` 拿到的是同一個 list，`_patch_last_model_message()` 直接修改。
3. **對話歷史儲存截斷為 20 則**：`save_conversation()` 只存最後 20 則（in `json_store.py` 的 `history[-20:]`），但 in-memory 保留 50 則。重啟後只能恢復 20 則。
4. **RAG embed 失敗不影響對話**：embed 回傳 None 時，改走 JSON 關鍵字搜尋。即使搜尋也失敗，`similar_memories` 為空但對話照常。
5. **`_chat_count` 和 `Decision.chat_count` 是獨立的**：MagicAI 的 count 驅動記憶彙整和對話儲存，Decision 的 count 驅動生平更新。兩者步調不同步（因為 Decision 在 stream_chat 的 exception 路徑不會呼叫 `_record_response`）。
