# iSafe Agent

獨立於對話的安全守護層，與 MagicAI **平行執行**。

**檔案**：`backend/agents/i_safe.py`

---

## 依賴關係

| 呼叫誰 | 被誰呼叫 |
|---------|---------|
| `LLMService.analyze_emotion()` | `Decision._run_isafe()` |
| `EmbeddingService.embed()` | 事件寫入後生成向量 |
| `VectorMemoryStore.add_event()` / `save_event_embedding()` | 記錄安全事件 |

---

## Module-level 常數與函式

### 關鍵字表

| 表名 | 數量 | 用途 | 匹配方式 |
|------|------|------|---------|
| `_EMERGENCY_ZH` / `_EN` | 16 / 10 | Level 3（緊急） | 中文 `in`，英文 `\b word \b` |
| `_URGENT_ZH` / `_EN` | 9 / 6 | Level 2（急迫） | 同上 |
| `_SAFE_ZH` / `_EN` | 13 / 12 | Level 0 快速路徑 | 同上，但需滿足額外條件 |
| `_SAFE_FAST_PATH_BLOCKERS_ZH` / `_EN` | 21 / 13 | 阻擋 Level 0 | 含這些詞不走快速路徑 |
| `_PHYSICAL_SYMPTOM_L2` | 20 | Safety bump | 中文 `in` |

### `_keyword_match(message, zh_keywords, en_keywords) → bool`

- 中文：直接 `kw in message` 子串匹配
- 英文：`re.search(r"\b" + kw + r"\b", message.lower())` 全詞匹配

### `quick_keyword_check(message) → int | None`

**被 Decision 和 iSafe 共用**（`from backend.agents.i_safe import quick_keyword_check`）。

```
message
├─ 匹配 _EMERGENCY → return 3
├─ 匹配 _URGENT   → return 2
├─ len ≤ 10 且匹配 _SAFE 且不匹配 _BLOCKER → return 0
└─ 以上都不匹配 → return None（需 LLM 判定）
```

Level 0 的三重條件（短句 + 安全詞 + 無 blocker）是為了防止 "早安但頭好暈" 被誤判為安全。

---

## Instance 狀態

| 屬性 | 說明 |
|------|------|
| `emotion_history` | `list[str]`，最近 5 次情緒，用於趨勢分析 |
| `active_persona_id` | 當前 persona，每次 `analyze()` 會重新讀取 |
| `llm` | `LLMService`，使用 `ISAFE_MODEL`（預設 `gemini-2.5-flash`） |

---

## Public API

### `analyze(message, speed_emotion="normal") → dict`

完整安全分析管線。

**流程**：

```
1. quick_keyword_check(message)
   ├─ 0 → 直接回傳安全結果，不呼叫 LLM
   │      {emotion: "normal", _llm_used: False, _isafe_path: "safe_keyword"}
   └─ 其他 → llm.analyze_emotion(message)
             {emotion, escalation_level, ..., _llm_used: True, _isafe_path: "llm"}

2. _apply_importance_rules(message, result)
   ├─ 緊急/急迫關鍵字 → importance ≥ 0.8, add "安全警報" tag
   ├─ 家人/回憶詞彙 → importance ≥ 0.7
   ├─ comfort/urgent 情緒 → importance ≥ 0.5
   ├─ importance ≥ 0.7 → memory_type = "long"
   └─ importance ≥ 0.5 或特定情緒 → should_record = True

3. 語速修正
   ├─ slow + emotion=="normal" → emotion 改為 "comfort"
   └─ fast + emotion=="normal" → emotion 改為 "urgent"

4. _determine_escalation(message, result) → escalation_level

5. _analyze_trend(result["emotion"]) → trend_alert | None

6. should_record == True → _record_event(...)
```

**回傳 dict 完整欄位**：

```python
{
    "emotion": str,             # "normal" | "happy" | "comfort" | "urgent"
    "emotion_score": float,     # -1.0 ~ 1.0
    "importance": float,        # 0.0 ~ 1.0
    "reason": str,              # 判定原因
    "is_urgent": bool,
    "sentiment": str,           # "positive" | "negative" | "neutral"
    "memory_type": str,         # "short" | "long"
    "should_record": bool,
    "escalation_level": int,    # 0-3（_determine_escalation 計算後加入）
    "trend_alert": str | None,  # _analyze_trend 結果
    "topic_tags": list[str],    # ["安全警報"], ["情緒"], ["趨勢警報", "需要關注"]
    "_llm_used": bool,
    "_isafe_path": str,         # "safe_keyword" | "llm"
}
```

### `get_safety_status() → dict`

掃描最近 200 筆事件，計算危險等級。

```python
{
    "elder_id": str,
    "urgent_count": int,      # 未確認的安全警報數
    "trend_alerts": int,      # 未確認的趨勢警報數
    "negative_count": int,    # 最近 20 筆中 sentiment=="negative" 的數量
    "hazard_level": str,      # "high" | "medium" | "low"
}
```

`hazard_level` 規則：有未確認安全警報 → high；有未確認趨勢警報 → medium；其他 → low。**確認後自動降回**。

### `record_emergency(message)`

Level 3 快速路徑專用。直接寫入 `importance=1.0` 的緊急事件，不走 LLM。被 `Decision.chat()` 在 `quick_keyword_check() == 3` 時呼叫。

---

## Internal Methods

### `_apply_importance_rules(message, result) → dict`

後處理 LLM 的分析結果，根據規則修正 importance。

**規則優先順序**（`max` 語意，只升不降）：

| 條件 | importance 下限 | 附加動作 |
|------|----------------|---------|
| `is_urgent` 或匹配緊急/急迫關鍵字 | 0.8 | 加 "安全警報" tag |
| 訊息含家人/回憶詞彙（11 + 11 個） | 0.7 | — |
| emotion 為 comfort 或 urgent | 0.5 | — |

最終：
- `importance ≥ 0.7` → `memory_type = "long"`
- `importance ≥ 0.5` 或 emotion 為 `urgent/comfort/happy` → `should_record = True`

### `_determine_escalation(message, result) → int`

```
1. keyword_level = quick_keyword_check(message) or 0
2. model_level = result["escalation_level"]（若為合法 int 0-3）
   └─ 不合法 → 從 emotion/importance/is_urgent 推算
3. level = max(keyword_level, model_level)
4. Safety bump: level == 1 且含 _PHYSICAL_SYMPTOM_L2 → level = 2
```

**Safety bump 設計原則**：LLM 可能把 "膝蓋腫起來" 判為 L1，但照護系統「能重判不能輕判」。20 個身體症狀關鍵字是人工策展的安全網。

### `_analyze_trend(current_emotion) → str | None`

維護 `emotion_history`（最多 5 個），取最後 3 個：

| 條件 | 結果 |
|------|------|
| 連續 3 次 `"urgent"` | `"緊急趨勢警報：連續三次偵測到緊急狀況！"` |
| 連續 3 次 `"comfort"` 或 `"urgent"` | `"情緒趨勢警報：長者持續情緒低落"` |
| 其他 | `None` |

**冷卻機制**：觸發前先呼叫 `_check_trend_cooldown()`，掃描事件紀錄中帶 "趨勢警報" tag 的項目，2 小時內有就跳過。

### `_save_event(event_dict)`

1. `memory.add_event()` 寫入（JSON + PostgreSQL 雙寫）
2. 若回傳 int（PostgreSQL memory_id）→ embed 事件文字 → `save_event_embedding()`
3. embed 失敗不影響，靜默處理

### `_record_event(...)`

組裝 event dict 並呼叫 `_save_event()`。event 內容格式：`"說了：{message[:50]}"`。

---

## Gotchas

1. **`emotion_history` 是 session-level**：server 重啟後歸零。趨勢分析只在連續對話中有效。
2. **`_PHYSICAL_SYMPTOM_L2` 只做 `kw in message`**：「腫」會匹配「浮腫」但也會匹配「腫瘤」（不是身體症狀的上下文）。false positive 是刻意的 — 寧可誤報。
3. **`quick_keyword_check` 的 Level 0 快速路徑需要 `len ≤ 10`**：長句即使包含安全詞也不走快速路徑，因為長句可能同時包含不安全內容。
4. **`analyze()` 每次都重新讀取 profile**：與 MagicAI 不同，iSafe 不快取 profile。這是因為 `active_persona_id` 可能被 admin 切換。
5. **`_apply_importance_rules` 的家人/回憶詞彙是硬編碼的**：`["爸爸", "媽媽", "女兒", ...]` 和 `["以前", "年輕", "老家", ...]`，新增需改 code。
