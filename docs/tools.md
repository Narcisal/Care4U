# Tools（外部工具）

圖片生成、健康搜尋、背景搜尋三個工具模組。

**檔案**：
- `backend/tools/image_gen.py`
- `backend/tools/health_search.py`
- `backend/tools/search_service.py`

---

## Image Generation

### 依賴

- Google Gemini API（`gemini-flash-lite-latest` 做觸發判斷，`gemini-2.5-flash-image` 做圖片生成）
- HTTP timeout 20 秒（在 `_get_client` 中設定）

### `detect_image_trigger(message) → str | None`

用輕量 LLM 判斷訊息是否包含具體視覺場景。

- 回傳 `"scene"` 或 `None`
- `temperature=0.0`，`max_output_tokens=10`
- 503 重試最多 3 次，每次等 2 秒
- 觸發條件（prompt 中定義）：
  - 具體地點（老家、阿里山、稻田）
  - 具體物件（縫紉機、三合院）
  - 具體場景（夕陽、廟會）
  - 夢境或懷舊中有具體畫面

### `extract_scene(message) → str`

從長者原話萃取 15-40 字的場景描述，過濾口語雜訊。去除人物描述。

Fallback：`message[:50]`（LLM 不可用時）

### `generate_image(message, trigger_type) → str | None`

1. `extract_scene()` 萃取場景
2. 用英文 prompt 呼叫 `gemini-2.5-flash-image`（`response_modalities=["IMAGE"]`）
3. Style：`"Taiwan retro landscape, soft warm colors, watercolor painting, vintage 1970s feel"`
4. 禁止：human faces、modern vehicles、text/numbers
5. 503/timeout 重試 1 次（等 5 秒）
6. 回傳 `"data:{mime_type};base64,{data}"` 或 `None`

**安全過濾**：若 Gemini 因 safety 攔截圖片，`cand.content` 會是 None，回傳 `None`。

---

## Health Search

### 依賴

- Tavily Search API（`TAVILY_API_KEY`）

### 常數

```python
HEALTH_KEYWORDS = {
    "復健": ["復健動作", "物理治療", "復健運動"],
    "用藥": ["藥物說明", "服藥方式", "藥物副作用"],
    "飲食": ["長者飲食", "銀髮族營養", "老人飲食建議"],
    "睡眠": ["改善睡眠", "老人失眠", "睡眠品質"],
    "血壓": ["高血壓控制", "血壓管理", "量血壓"],
    "糖尿病": ["糖尿病飲食", "血糖控制", "糖尿病照護"],
    "跌倒": ["防跌運動", "跌倒預防", "平衡訓練"],
    "失智": ["失智症照護", "認知訓練", "腦部健康"],
}

TRIGGER_KEYWORDS = [
    "怎麼做", "如何", "教我", "示範", "復健",
    "運動", "藥", "飲食", "吃什麼", "血壓",
    "血糖", "跌倒", "失智", "睡不好", "睡眠"
]
```

### `detect_health_topic(message) → str | None`

1. 訊息不含任何 `TRIGGER_KEYWORDS` → `None`
2. 匹配 `HEALTH_KEYWORDS` 的 topic 或子關鍵字 → 回傳 topic 名稱
3. 含通用觸發詞（怎麼做/如何/教我/示範）但不匹配特定 topic → `"general"`

### `search_health_info(message, topic) → dict | None`

```python
# 查詢格式
"台灣 {HEALTH_KEYWORDS[topic][0]} 衛教 長者"  # 已知 topic
"台灣 {message[:20]} 衛教資訊 長者"            # general topic
```

- `search_depth="basic"`，`max_results=3`，`include_answer=True`
- 回傳：`{title, summary, url, source}`
- `summary` 截斷為 300 字

---

## Search Service

背景搜尋 + 傳記生成。比其他兩個工具模組複雜很多。

### 依賴

- Tavily Search API
- Google Gemini API（傳記生成用）

### Instance 狀態

`SearchService` 只有一個屬性 `self.client`（TavilyClient 或 None）。

### `search_elder_background(name, keywords) → dict`

搜尋長者背景資料。

- Query：`"{name} {' '.join(keywords)}"`
- `search_depth="basic"`，`max_results=3`，`include_answer=True`
- 回傳 `{found, summary, sources}`
- `summary` 截斷 500 字，低於 50 字視為 `found=False`

### `build_search_queries(profile, extra_keywords) → list[str]`

從 profile 抽取搜尋關鍵字：`name`、`former_job`、`hobbies`、`family_notes` 最後 5 筆的 tokens、`extra_keywords`。最多 6 個 seed。用 `dict.fromkeys()` 去重保序。

### `search_background_candidates(profile, extra_keywords) → dict`

批量搜尋候選來源（前端「搜尋背景」功能用）。

- 每個 query 最多 3 結果，總上限 8 筆
- URL 去重（`seen_urls` set）
- 每筆附 `confidence` 標籤（`_rough_match_label`）：`"可能相符"` / `"需要確認"` / `"不確定"`

### `search_cultural_context(birth_year, hometown, job) → str`

搜尋職業/年代/地方文化脈絡，**不搜本人姓名**（避免身份混淆）。

- 從 `birth_year` 取 10 年代（如 1940）
- 最多 3 個 query，每個最多 2 結果
- snippets 上限 6 筆，每筆 answer 300 字 / content 200 字

### `generate_biography(name, gender, job, hobbies, personas, health, raw_summary) → str`

為已存在長者生成傳記草稿。呼叫 `_generate_biography_core()` → fallback `_fallback_biography()`。

### `generate_biography_for_new_elder(...) → str`

為新長者生成傳記。先 `search_cultural_context()` 取文化脈絡，再 `_generate_biography_core()`。

### `_generate_biography_core(...) → str`

核心傳記生成。直接呼叫 Gemini API（不經過 `llm_service.py`）。

**Prompt 結構**（兩層分離設計）：
- **Layer 1**：已知事實（admin 填的 profile 資料）— 唯一允許的個人細節來源
- **Layer 2**：Tavily 搜尋的時代文化背景 — 只能描寫時代氛圍，禁止套用到個人

`temperature=0.15`，`max_output_tokens=900`。品質檢查：`_is_weak_biography()` 判斷長度 < 80 字或結尾為標點符號（表示被截斷）。

### `_fallback_biography(name, job, hobbies, personas) → str`

LLM 不可用時的模板式傳記（約 2-3 句）。

---

## 整合方式

圖片生成和健康搜尋都是**背景任務**，由 `main.py` 在對話完成後異步執行：

```python
# main.py 中的 chat endpoint
task_id = _reserve_background_result(owner_token)

def _bg_image():
    image, caption = decision._run_image_gen(message)
    _update_background_result(task_id, {"image": image, "image_caption": caption, "image_status": "complete"})

def _bg_health():
    health = decision._run_health_search(message)
    _update_background_result(task_id, {"health_info": health, "health_status": "complete"})

threading.Thread(target=_bg_image, daemon=True).start()
threading.Thread(target=_bg_health, daemon=True).start()
```

前端透過 `GET /api/chat/background/{task_id}` 輪詢。

---

## Gotchas

1. **`image_gen` 有自己的 `_get_client()`**：不共用 `llm_service.py` 的 client。HTTP timeout 設定不同（20 秒 vs 15 秒）。
2. **`detect_image_trigger` 使用 `gemini-flash-lite-latest`**：比其他模組用的模型更輕量，但也更容易誤判。
3. **健康搜尋的查詢語言是中文**：Tavily 的中文搜尋品質可能不穩定。
4. **背景任務沒有 timeout**：如果 Gemini 圖片生成掛了（超過 20 秒 HTTP timeout），thread 會卡住。前端的 60 次輪詢（每秒一次）會先超時。
5. **`search_service.py` 和 `health_search.py` 都 import Tavily**：各自建立獨立的 TavilyClient instance，不共用。
6. **`_generate_biography_core` 直接呼叫 Gemini API**：不經過 `llm_service.py`，沒有 OpenAI fallback、沒有 semaphore 保護、沒有 retryable error 判斷。失敗直接 return 空字串走 `_fallback_biography`。
7. **`_generate_biography_core` 有未定義變數 bug**：`existing_bio` 在 `api_key` 為空時被引用但從未定義（line 267）。這會 raise `NameError`。
