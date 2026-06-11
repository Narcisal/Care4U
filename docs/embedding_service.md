# Embedding Service

向量嵌入服務，將文字轉為 3072 維向量用於語意搜尋。

**檔案**：`backend/services/embedding_service.py`

---

## 依賴關係

| 呼叫誰 | 被誰呼叫 |
|---------|---------|
| Google Gemini Embedding API | `MagicAI.chat()` / `stream_chat()`（RAG 查詢） |
| — | `ISafe._save_event()`（事件向量化） |

---

## 實作

```python
class EmbeddingService:
    model = "models/gemini-embedding-2"
    dimensions = 3072
```

### `embed(text) → list | None`

- Demo mode 或無 API key → `None`
- 呼叫 `client.models.embed_content(model, contents=text)`
- 回傳 `embeddings[0].values`（3072 維 float list）
- 任何 exception → `None`

### `embed_batch(texts) → list`

**逐筆呼叫** `embed()`。沒有用 Gemini 的 batch embedding API。

---

## Gotchas

1. **`embed_batch` 是 O(n) 個 API 呼叫**：Gemini API 支援 batch embedding（一次傳多筆），但這裡沒用。目前只有 `seed_l001_embeddings.py` 工具腳本會大量嵌入，生產路徑通常一次一筆。
2. **回傳 None 的處理**：所有呼叫端都需要處理 `None` — MagicAI 改走 JSON 關鍵字搜尋，iSafe 跳過向量儲存。
3. **不共用 `llm_service.py` 的 client**：有自己的 `_get_client()` 和 `_client` singleton。Demo mode 邏輯一樣（`CARE4U_DEMO_MODE=true` → None）。
4. **沒有 rate limit 或 retry**：embed 失敗直接回傳 None，不重試。
