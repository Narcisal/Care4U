# LLM Service

統一的 LLM 呼叫層，封裝 Gemini 和 OpenAI 兩個 provider 的 fallback 邏輯。

**檔案**：`backend/services/llm_service.py`

---

## 依賴關係

| 呼叫誰 | 被誰呼叫 |
|---------|---------|
| Google Gemini API（`google.genai`） | `MagicAI.chat()` / `stream_chat()` |
| OpenAI API（`openai`） | `ISafe.analyze()` via `analyze_emotion()` |
| — | `Decision._update_biography()` via `update_biography()` |
| — | `MagicAI._summarize_memories()` via `generate_memory_summary()` |

---

## Module-level 全域狀態

| 變數 | 型別 | 說明 |
|------|------|------|
| `_client` | `genai.Client \| None` | Gemini singleton client |
| `_openai_client` | `OpenAI \| None` | OpenAI singleton client |
| `_llm_semaphore` | `BoundedSemaphore(LLM_MAX_CONCURRENT)` | Gemini + OpenAI **共用**並行上限，預設 4 |
| `LLM_TIMEOUT_MS` | `int` | Gemini HTTP timeout，預設 15000ms |
| `OPENAI_MODEL` | `str` | OpenAI fallback 模型，預設 `"gpt-4o-mini"` |
| `_HAS_OPENAI` | `bool` | `openai` 套件是否已安裝（try/except import） |

### Client 初始化策略

兩個 client 都是**延遲 singleton**：

```python
def _get_client():
    # CARE4U_DEMO_MODE=true → return None（不呼叫 Gemini）
    # GEMINI_API_KEY 缺少或 == "your_api_key_here" → return None
    # 否則建立 genai.Client 並快取

def _get_openai_client():
    # _HAS_OPENAI == False → return None（套件未安裝）
    # OPENAI_API_KEY 缺少或 == "your_api_key_here" → return None
    # 否則建立 OpenAI client 並快取
```

---

## Fallback Chain

所有 public method 遵循同一模式：

```
Gemini 嘗試
  ├─ 成功 → return
  ├─ 失敗 + _is_retryable_gemini_error() → 嘗試 OpenAI
  │   ├─ 成功 → return
  │   └─ 失敗 → 關鍵字 fallback
  └─ 失敗 + 非 retryable → 直接關鍵字 fallback（不浪費 OpenAI quota）

Gemini client 為 None（demo mode / 無 key）
  └─ 嘗試 OpenAI → 成功 return / 失敗 → 關鍵字 fallback
```

### `_is_retryable_gemini_error(exc) → bool`

檢查 error message 是否包含以下信號：

```
"503", "overloaded", "unavailable", "timeout",
"rate limit", "429", "deadline", "connection",
"resource exhausted", "internal error", "500"
```

**非 retryable 的情況**（prompt 本身有問題，OpenAI 也會失敗）：安全過濾、格式錯誤等。

### `_warn_fallback(method, reason, target="OpenAI")`

在 server console 印出醒目的 60 字元寬橫幅：

```
============================================================
  [!] FALLBACK TRIGGERED  [14:30:00]
  Method : stream_chat
  Reason : 503 Service Unavailable
  Target : OpenAI (gpt-4o-mini)
============================================================
```

---

## Public API

### `LLMService(model_name="gemini-2.5-flash")`

唯一的 instance 屬性是 `self.model_name`，用於 Gemini 呼叫。OpenAI 始終使用 `OPENAI_MODEL` 環境變數。

### `analyze_emotion(message) → dict`

**Gemini path**：
- 最多重試 3 次（503 / overloaded / JSON parse error）
- 等待時間：`2 * (attempt + 1)` 秒
- `response_mime_type="application/json"` 強制 JSON 輸出
- `thinking_budget=0` 跳過思考（加速）

**OpenAI path**：
- `response_format={"type": "json_object"}` 強制 JSON
- `temperature=0.0`

**最終 fallback**：`_fallback_emotion(message)` 純關鍵字分析。

### `chat(profile, conversation_history, user_message, ...) → str`

**Gemini path**：
- 將 `history_source` 轉為 `types.Content` 列表
- `system_instruction` 由 `build_system_prompt()` 生成
- `temperature=0.9`，`max_output_tokens=2000`

**OpenAI path**：
- `_to_openai_messages()` 轉換：`role="model"` → `role="assistant"`
- system prompt 放在 `messages[0]` 的 `role="system"`

### `stream_chat(profile, conversation_history, user_message, ...) → Generator[str]`

**Gemini streaming path**：
- `thinking_budget=512`（比 chat 的非串流允許一些思考）
- 追蹤 `yielded` 布林值：**已 yield 過文字就不再 fallback**
  - 因為部分串流後切換 provider 會造成語意中斷

**OpenAI streaming path**：
- `_openai_generate_stream()` yield `delta.content` chunks

### `generate_memory_summary(events, name) → str`

LLM prompt 要求以第三人稱、自然口語生成照護摘要。`temperature=0.3`。

Fallback 文字：`"{name} 近期主要提到「{last_event}」..."`

### `update_biography(name, existing_bio, important_events, family_notes) → str`

合併新資訊到現有生平。`temperature=0.2`（更保守）。

Fallback：直接回傳 `existing_bio` 不修改。

### `generate_persona_tone(relation, name, ...) → str`

50 字以內的說話風格描述。`temperature=0.3`。

Fallback：`"像{name}這位{relation}，語氣{personality}..."`

---

## System Prompt 建構

### `build_system_prompt(profile, ...) → str`

組裝完整的 system prompt，約 2000-3000 字。

**Persona 模式**（`_build_persona_desc`）：

| 條件 | 模式 | 核心差異 |
|------|------|---------|
| 已故親人 + 認知正常 | 跨時空靈魂模式 | 承認已過世，用「我在你心裡」回應 |
| 已故親人 + 失智 | 溫柔陪伴模式 | 不提及死亡，模糊回應「我一直都在」 |
| 在世家人 | 角色扮演 | 自然演家人，有個性 |
| AI 預設 | 志工 | 「像疼愛長輩的晚輩」 |

**記憶 context**（`_build_memory_context`）：

| Section | 來源 | 說明 |
|---------|------|------|
| `recent_events_text` | `profile["recent_events"][-3:]` | 最近 3 筆事件 |
| `recent_conv_text` | `recent_messages` 參數 | 最近幾輪對話 |
| `long_term_text` | `important_memories` 參數 | 重要記憶 |
| `similar_text` | `similar_memories` 參數 | RAG 相似記憶，過濾 distance ≥ 0.9 |
| `summary_text` | `profile["memory_summary"]["content"]` | 記憶摘要 |
| `biography_text` | `profile["elder_biography"]["content"]` | 生平 |
| `family_notes_text` | `profile["family_notes"]` | 家人備忘 |

**生平使用規則**（`_build_bio_instruction`）：

| `biography_usage_count` | 指示 |
|------------------------|------|
| 0 | 第一次對話，可自然帶入一個 |
| 1-2 | 已帶入過，只在話題非常相關時 |
| ≥ 3 | 不要再主動帶入 |

---

## Helper Functions

### `_to_openai_messages(system_prompt, history_dicts, user_message) → list`

將 Gemini 格式的對話轉為 OpenAI 格式：
- `system_prompt` → `{"role": "system", "content": ...}`
- `role="model"` → `role="assistant"`
- `user_message` → 最後一則 `{"role": "user", ...}`

### `_parse_emotion_result(raw_text) → dict`

共用 JSON 解析器（Gemini 和 OpenAI 都用）：
1. 嘗試 `json.loads(raw_text)`
2. 失敗 → regex 找 `{...}` 再解析
3. 正規化 `escalation_level`（clamp 0-3）
4. 根據 escalation_level 推算 `importance`：L2+ → 0.8，L1 → 0.5，L0 → 0.3
5. 根據 sentiment 推算 `emotion_score`：positive → 0.6，negative → -0.6

### `_fallback_emotion(message) → dict`

純關鍵字最終 fallback（Gemini 和 OpenAI 都不可用時）：

| 關鍵字 | emotion | importance |
|--------|---------|-----------|
| 痛、胸口、喘、跌倒、頭暈、暈、救命、不舒服、腳軟 | urgent | 0.8 |
| 孤單、難過、想念、傷心、不開心、心慌、焦慮、睡不著 | comfort | 0.6 |
| 開心、很好、不錯、謝謝、喜歡、好吃 | happy | 0.4 |
| 其他 | normal | 0.3 |

---

## Gotchas

1. **Semaphore 共用**：Gemini 和 OpenAI 用同一個 `_llm_semaphore`。如果 Gemini 全部 timeout，會佔滿 semaphore 直到 timeout 結束，期間 OpenAI 也無法執行。
2. **`stream_chat` 的 `yielded` 防護**：一旦 Gemini 已 yield 任何文字，即使後續 chunk 拋 exception，也不會 fallback 到 OpenAI（會直接 yield 關鍵字 fallback 加在已有文字之後）。
3. **`analyze_emotion` 的重試只在 Gemini path**：503 / JSON parse error 會重試最多 3 次。OpenAI path 不重試。
4. **`build_system_prompt` 很長**：約 2000-3000 字的 prompt。每次 `chat()` / `stream_chat()` 都重新建構，不快取。
5. **`thinking_budget` 不同**：`analyze_emotion` 用 `thinking_budget=0`（純分類），`stream_chat` 用 `thinking_budget=512`（允許一些思考）。`chat` 非串流版**沒有設定 thinking_config**。
