# Memory Layer

雙層記憶架構：JSON 檔案為基礎，PostgreSQL + pgvector 為可選的向量搜尋層。

**檔案**：
- `backend/memory/vector_store.py` — VectorMemoryStore
- `backend/memory/json_store.py` — JsonMemoryStore
- `backend/memory/memory_manager.py` — MemoryManager 抽象介面

---

## 架構概覽

```
VectorMemoryStore（外部使用者看到的唯一介面）
    │
    ├── 所有 profile / conversation / persona / biography 操作
    │   └── 委派給 JsonMemoryStore
    │
    ├── add_event()
    │   ├── JsonMemoryStore.add_event()  ← 永遠執行
    │   └── PostgreSQL INSERT           ← DB_ENABLED=true 時
    │
    ├── search_similar_memories()
    │   ├── PostgreSQL vector search    ← 有 embedding 時
    │   └── JsonMemoryStore fallback    ← 無結果或 DB 不可用時
    │
    └── get_important_memories()
        ├── PostgreSQL query            ← DB 可用時
        └── JsonMemoryStore fallback    ← DB 不可用時
```

---

## VectorMemoryStore

### 連線池

Module-level singleton，雙重檢查鎖初始化：

```python
_db_pool: ThreadedConnectionPool | None  # 全域共用
_pool_init_lock = threading.Lock()

def _init_pool():
    # 雙重檢查 + _pool_init_lock
    # maxconn = DB_POOL_MAX (預設 5)
    # connect_timeout = DB_CONNECT_TIMEOUT (預設 1s)
```

`_get_conn()` 是 context manager：
- `db_enabled=False` 或 pool 為 None → yield None
- 借還連線，`autocommit=True`
- 借用失敗 → yield None（不 raise）

### `add_event(elder_id, event) → int | bool`

1. 先 `JsonMemoryStore.add_event()` — 失敗直接 return False
2. PostgreSQL INSERT → return `id`（int）或 False

### `save_event_embedding(memory_id, embedding) → bool`

`UPDATE elder_memories SET embedding = %s::vector WHERE id = %s`

### `search_similar_memories(elder_id, query_embedding, limit=5, persona_id=None, query_text="") → list`

**查詢策略**：

```
DB 不可用 → JSON 關鍵字搜尋
query_embedding 為空 → JSON 關鍵字搜尋
PostgreSQL 查詢：
  SELECT ... embedding <=> %s::vector AS distance
  WHERE elder_id = %s AND embedding IS NOT NULL
  DISTINCT ON (content)  ← 去重
  ORDER BY distance ASC
  LIMIT %s
結果為空 且 query_text 非空 → JSON 關鍵字搜尋
PostgreSQL 查詢失敗 → JSON 關鍵字搜尋
```

persona 過濾：`persona_id = %s OR persona_id IS NULL OR persona_id = 'ai'`

### `get_important_memories(elder_id, importance_threshold=0.7, limit=10, persona_id=None) → list`

與 `search_similar_memories` 類似，DB 可用走 PostgreSQL `WHERE importance >= %s ORDER BY importance DESC`，不可用走 JSON。

---

## JsonMemoryStore

### 檔案結構

```
backend/data/elders/
├── W001.json              ← profile（含 personas, biography, events, notes）
├── W001_ai_conv.json      ← AI persona 的對話歷史
├── W001_persona_1_conv.json  ← 自訂 persona 的對話歷史
├── C001.json
└── ...
```

### 併發控制

**Per-file lock**：每個檔案路徑一把 `threading.Lock`，不同長者互不阻塞。

```python
_file_locks: dict[str, threading.Lock]  # key = 檔案絕對路徑
_file_locks_mutex = threading.Lock()    # 保護 _file_locks dict 本身
```

### 原子寫入

所有寫入都經過：
1. 寫入 `.tmp` 暫存檔
2. `os.replace(tmp, path)` 原子替換
3. 失敗時刪除 `.tmp`

### `_mutate_profile(elder_id, mutator, create=False) → bool`

通用的 read-modify-write pattern：
1. 持鎖讀取 profile
2. 呼叫 `mutator(profile)` — 若回傳 False → 中止
3. 持鎖寫入

被以下方法使用：`append_family_note`, `delete_family_note_at`, `set_persona`, `add_persona_auto`, `delete_persona`, `set_active_persona`, `set_persona_field`, `set_biography`, `update_basic_fields`

### 對話歷史

#### `save_conversation(elder_id, history, persona_id="ai") → bool`

**重要：只存最後 20 則**（`history[-20:]`）。檔名格式 `{elder_id}_{persona_id}_conv.json`。

```json
{
    "elder_id": "W001",
    "persona_id": "ai",
    "updated_at": "2025-01-15 14:30:00",
    "history": [...]
}
```

#### `load_conversation(elder_id, persona_id="ai") → list`

讀取時 backfill 缺失欄位：
- 缺 `date` → 用 `updated_at[:10]`
- 缺 `time` → 空字串
- model message 缺 `escalation_level` → 0
- model message 缺 `sentiment` → "neutral"

### 事件管理

#### `add_event(elder_id, event) → bool`

1. 生成 `id`（uuid[:8]）
2. 從 `spoken_at` 解析 date/time
3. 設定 `acknowledged = False`
4. append 到 `profile["recent_events"]`
5. `_trim_events()` 修剪

#### `_trim_events(events) → list`

當 events 超過 `MAX_EVENTS = 80` 時，按優先順序保留：

```
1. 未確認的安全/趨勢警報（escalation_level ≥ 2 或含 安全警報/緊急警報/趨勢警報 tag）
2. 重要記憶（importance ≥ 0.7 或 memory_type == "long"）→ 最多 IMPORTANT_KEEP_LIMIT = 40 筆
3. 最新的一般事件 → 填滿到 MAX_EVENTS
```

保留順序：維持原始 index 順序（用 set 追蹤 selected indexes）。

### 關鍵字 RAG Fallback

#### `search_similar_memories(elder_id, query, limit=5, persona_id=None) → list`

token-overlap 算法（當 pgvector 不可用時）：

1. `_tokens(text)` 分詞：
   - 英文：`re.findall(r"[a-z0-9]+", text.lower())`
   - 中文：取所有 2+ 字的中文片段，拆成 bigram + 原始 chunk（≤ 4 字時）
2. 計算 `overlap = query_tokens & event_tokens`
3. `score = len(overlap) + importance`
4. `distance = max(0, 1 - min(score/6, 1))`

### 生平管理

#### `set_biography(elder_id, biography_dict, skip_if_manual=False, preserve_sources=False) → BiographyUpdateResult`

- `skip_if_manual=True`：若 `manually_edited == True` → 回傳 `"skipped"`
- `preserve_sources=True`：保留原有的 `sources` 列表
- 成功 → `"updated"`，失敗 → `"failed"`
- 同時重設 `biography_usage_count = 0`

---

## Gotchas

1. **VectorMemoryStore 沒有自己的狀態**：所有 profile/conversation 操作都是 passthrough 到 JsonMemoryStore。它只在 `add_event` 和 search 類方法中加入 PostgreSQL 邏輯。
2. **JSON fallback 的 search 品質遠低於 pgvector**：bigram overlap 是很粗糙的近似，語意理解能力接近零。建議生產環境啟用 PostgreSQL。
3. **`save_conversation` 只存 20 則，但 in-memory 有 50 則**：重啟後對話上下文縮短。
4. **`_trim_events` 不保證時間順序**：它用 set 追蹤 index，最終按原始 index 順序重建。但混合不同優先級的選擇可能導致時間不連續。
5. **`autocommit=True`**：每個 SQL 語句自動 commit，不支援跨語句 transaction。`add_event` 的 JSON 寫入和 PostgreSQL 寫入不是原子操作 — JSON 成功但 PostgreSQL 失敗時，資料會不一致。
6. **連線池沒有 health check**：`getconn()` 拿到的連線可能已斷開。依賴 PostgreSQL 自動重連機制。
