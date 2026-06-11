# Care4U Bug Tracker

> Auto-generated bug scan — 2026-06-11
> **Rule: 只記錄，不動程式碼**

---

## Phase A — Critical Bugs（立即修復）

### A-1: Gemini API contents 格式錯誤
- **File**: `backend/services/llm_service.py:638`
- **Severity**: CRITICAL
- **Description**: `generate_memory_summary()` 將 `prompt` 字串直接傳入 `contents=prompt`，但 Gemini API 預期的是 `Content` 物件清單，會在 runtime 直接炸掉。
- **Impact**: 記憶摘要功能完全無法使用。
- [ ] 修復

### A-2: Gemini API contents 格式錯誤（update_biography）
- **File**: `backend/services/llm_service.py:694`
- **Severity**: CRITICAL
- **Description**: `update_biography()` 同樣將 `prompt` 字串直接傳入 `contents=prompt`，格式不符 Gemini SDK 要求。
- **Impact**: 自傳更新功能完全無法使用。
- [ ] 修復

### A-3: i_safe bool/int isinstance 判斷邏輯錯誤
- **File**: `backend/agents/i_safe.py:340`
- **Severity**: CRITICAL
- **Description**: `_save_event()` 中 `not isinstance(memory_id, int) or isinstance(memory_id, bool)` 邏輯有誤。Python 中 `bool` 是 `int` 子類別，`True` 會通過 `isinstance(x, int)`，導致 `memory_id=True` 時不會 return，而 `memory_id=False` 時會被錯誤跳過 embedding 生成。
- **Impact**: 部分安全事件的 embedding 不會被產生，i-SAFE 向量搜尋會漏掉資料。
- [ ] 修復

### A-4: admin.html 寫死 localhost API 端點
- **File**: `frontend/admin.html:1013`
- **Severity**: CRITICAL
- **Description**: `const API_BASE = "http://127.0.0.1:8000"` 寫死 localhost，部署到任何非本機環境都會完全失效。
- **Impact**: 生產環境管理後台完全無法使用。
- [ ] 改為相對路徑或動態讀取

---

## Phase B — High Severity Bugs（高風險）

### B-1: ~~STT pool resource leak~~ ✅ FIXED
- **File**: `backend/main.py:1253-1260`
- **Severity**: HIGH
- **Description**: ~~若在 `stt_pool_lock.get()` 之後、`stt_pool_lock.put()` 之前發生例外，STT worker 不會歸還至 pool。~~ 已用 `try/finally` 修復。
- [x] 修復

### B-2: TTS executor 缺少例外處理
- **File**: `backend/main.py:1350-1379`
- **Severity**: HIGH
- **Description**: `loop.run_in_executor()` 呼叫 `service.synthesize()` 時沒有 try-except，若 executor 內拋出例外，會直接傳播到 async context 且沒有日誌。
- **Impact**: TTS 崩潰時無法 debug，且可能導致未處理例外。
- [ ] 修復

### B-3: decision.py chat() 歷史修改缺少 lock
- **File**: `backend/agents/decision.py:165-247`
- **Severity**: HIGH
- **Description**: `chat()` 呼叫 `_patch_last_model_message()` 修改 `self.magic.get_history()` 時沒有持有 `self._lock`。若與 `stream_chat()` 同時呼叫，會造成對話歷史損壞。
- **Impact**: 並行請求會導致對話記錄被覆蓋或損壞。
- [ ] 修復

### B-4: TTS PowerShell 指令注入風險
- **File**: `backend/services/tts_service.py:216-225`
- **Severity**: HIGH
- **Description**: 未經消毒的 JSON payload（含使用者輸入的 text）被直接嵌入 PowerShell script。若 `text` 包含特殊字元或引號，可能造成腳本中斷或注入攻擊。
- **Impact**: 安全漏洞，可能被利用執行任意指令。
- [ ] 修復

### B-5: STT 暫存檔清理不保證
- **File**: `backend/services/stt_service.py:196-198`
- **Severity**: HIGH
- **Description**: `tempfile.NamedTemporaryFile(delete=False)` 建立暫存檔後，若在 try-finally 之前發生例外，暫存檔不會被清理。
- **Impact**: 磁碟空間逐漸被佔滿。
- [ ] 修復

### B-6: json_store 對話儲存 race condition
- **File**: `backend/memory/json_store.py:279-298`
- **Severity**: HIGH
- **Description**: `save_conversation()` 在取得 lock 之前就產生暫存檔路徑，多執行緒同時寫入同一 elder+persona 時可能互相干擾。
- **Impact**: 對話記錄可能被覆蓋或損壞。
- [ ] 修復

### B-7: ~~search_service `_generate_biography_core` NameError~~ ✅ FIXED
- **File**: `backend/tools/search_service.py:267`
- **Severity**: HIGH → **CRITICAL（runtime crash）**
- **Description**: ~~`_generate_biography_core()` 在 `api_key` 為空時執行 `return existing_bio`，但 `existing_bio` 從未定義~~ 已修復：改為 `return ""`。
- [x] 修復

### B-8: health_search URL 解析會 IndexError
- **File**: `backend/tools/health_search.py:76`
- **Severity**: HIGH
- **Description**: `.split("/")[2]` 假設 URL 格式正確且至少有 3 段，畸形 URL 會觸發 `IndexError`。
- **Impact**: 健康搜尋功能因單一畸形 URL 而整個崩潰。
- [ ] 改用 `urllib.parse`

### B-9: Frontend 多處 DOM null check 缺失
- **File**: `frontend/app.js:591, 667, 778, 1275`
- **Severity**: HIGH
- **Description**: `addMessage()`、`addImageMessage()`、`clearChat()`、`checkVolume()` 等函式呼叫 `getElementById()` 後未檢查是否為 null 就直接存取屬性。
- **Impact**: DOM 元素不存在時直接 crash，尤其在動態載入或頁面切換時。
- [ ] 修復

### B-10: ~~Frontend fetch 未檢查 response.ok~~ ✅ FIXED
- **File**: `frontend/app.js:566`
- **Severity**: HIGH
- **Description**: ~~`/api/stt` fetch 回應未檢查 `res.ok`~~ 已修復：`if (!res.ok) throw new Error(...)`。
- [x] 修復

### B-11: ~~Frontend TTS promise rejection 未處理~~ ✅ FIXED
- **File**: `frontend/app.js:269`
- **Severity**: HIGH
- **Description**: ~~`playAll()` 中 promise rejection 未被 catch~~ 已修復：`try { await playAudioBlob(await p); } catch (e) { ... }`。
- [x] 修復

### B-12: admin.html fetch wrapper 可被繞過
- **File**: `frontend/admin.html:1018-1026`
- **Severity**: HIGH
- **Description**: 自訂 `fetch()` wrapper 假設所有 API_BASE 的呼叫都需要 auth，但 `_rawFetch()` 可以繞過 auth 邏輯。
- **Impact**: 安全機制不一致，部分 API 呼叫可能缺少認證。
- [ ] 修復

---

## Phase C — Medium Severity Bugs（穩定性改進）

### C-1: magic_ai profile None 未檢查
- **File**: `backend/agents/magic_ai.py:24, 67`
- **Severity**: MEDIUM
- **Description**: `self.profile = self.memory.get_profile(elder_id)` 未做 null check，後續 `self.profile.get("name")` 會觸發 `AttributeError`。
- **Impact**: 長者資料不存在時 server crash。
- [ ] 修復

### C-2: decision.py _update_biography 例外處理不足
- **File**: `backend/agents/decision.py:538-575`
- **Severity**: MEDIUM
- **Description**: `self.magic.llm.update_biography()` 拋出例外時，雖有 finally 移除 `_biography_updates_in_progress` flag，但例外本身未被捕捉處理。
- **Impact**: 自傳更新可能卡在 "進行中" 狀態。
- [ ] 修復

### C-3: Background result 時間精度問題
- **File**: `backend/main.py:190-221`
- **Severity**: MEDIUM
- **Description**: `_update_background_result()` 使用 `time.monotonic()` 但清理邏輯的時間比較可能因精度問題導致結果被過早移除或保留過久。
- **Impact**: 背景任務結果可能提前過期。
- [ ] 修復

### C-4: vector_store get_important_memories 缺少 persona_id
- **File**: `backend/memory/vector_store.py:277-281`
- **Severity**: MEDIUM
- **Description**: JSON fallback 呼叫 `self._json.get_important_memories()` 時缺少 `persona_id` 參數。
- **Impact**: 取得重要記憶時可能回傳錯誤的 persona 資料。
- [ ] 修復

### C-5: embedding_service batch 效率問題
- **File**: `backend/services/embedding_service.py:40`
- **Severity**: MEDIUM
- **Description**: `embed_batch()` 逐一呼叫 `embed()`，發出 N 次 API request，未使用 Gemini 的 batch embedding API。
- **Impact**: 效能低落，容易觸發 rate limit。
- [ ] 修復

### C-6: elder_sessions dict iteration race condition
- **File**: `backend/elder_sessions.py:64-66`
- **Severity**: MEDIUM
- **Description**: `_cleanup_unlocked()` 雖用 `list()` 建立 snapshot，但 `elder_tokens` 仍可能被其他 thread 同時修改（新增/刪除），需確保所有存取都在同一把 lock 下。
- **Impact**: 潛在的 `RuntimeError: dictionary changed size during iteration`。
- [ ] 修復

### C-7: ~~Frontend audio playback race condition~~ ✅ FIXED
- **File**: `frontend/app.js:214-231`
- **Severity**: MEDIUM
- **Description**: ~~`playAudioBlob()` 在 `audio.play()` 前就 resolve~~ 已修復：promise 在 `audio.onended` 時才 resolve。
- [x] 修復

### C-8: Frontend TTS error timer 競爭
- **File**: `frontend/app.js:99-109`
- **Severity**: MEDIUM
- **Description**: `showTtsError()` 設定 timeout 但若在 timeout 期間又觸發 TTS，多個 timer 會同時 fire 造成 label 文字不一致。
- **Impact**: UI 狀態顯示錯亂。
- [ ] 修復

### C-9: index.html event 隱式全域物件
- **File**: `frontend/index.html:922`
- **Severity**: MEDIUM
- **Description**: `onclick="if (event.target === this) closeSwitcher()"` 依賴隱式全域 `event` 物件，部分瀏覽器可能不支援。
- **Impact**: 某些瀏覽器上 switcher 無法關閉。
- [ ] 修復

---

## Phase D — Low Severity Bugs（品質改善）

### D-1: get_profile 未驗證 elder_id 授權
- **File**: `backend/main.py:1427-1438`
- **Severity**: LOW
- **Description**: `get_profile()` endpoint 只檢查 admin 認證，未驗證 `elder_id` 是否在 `ALLOWED_ELDER_IDS` 中。
- **Impact**: 管理員帳號被入侵時可存取未授權的長者資料。
- [ ] 修復

### D-2: voice upload rollback 未驗證成功
- **File**: `backend/main.py:1735-1743`
- **Severity**: LOW
- **Description**: voice upload 失敗時 rollback 呼叫 `set_persona_field()` 但未檢查回傳值，若 rollback 也失敗會留下不一致狀態。
- **Impact**: 孤立的語音檔或 metadata 不一致。
- [ ] 修復

### D-3: image_gen load_dotenv 缺少 override
- **File**: `backend/tools/image_gen.py:8`
- **Severity**: LOW
- **Description**: `load_dotenv()` 未加 `override=True`，與其他 service 不一致，可能導致環境變數讀取到舊值。
- **Impact**: 環境變數不一致。
- [ ] 修復

### D-4: tts_service fail_count reset 時機
- **File**: `backend/services/tts_service.py:149`
- **Severity**: LOW
- **Description**: `_xtts_fail_count` 在 lock 內重設為 0，但 return 在 lock 外，時序上可能有微小的競爭窗口。
- **Impact**: fail count 可能在極端情況下不準確。
- [ ] 修復

### D-5: stt_service 未檢查 transcript key
- **File**: `backend/services/stt_service.py:154-159`
- **Severity**: LOW
- **Description**: `_transcribe_whisper()` 直接存取 `result["text"]` 未確認 key 是否存在，API 回傳格式變動時會 `KeyError`。
- **Impact**: 非預期 API 回傳格式時 crash。
- [ ] 修復

### D-6: json_store 中文字元 regex 範圍不正確
- **File**: `backend/memory/json_store.py:532`
- **Severity**: LOW
- **Description**: `[一-鿿]` 範圍不完全正確，應使用 `[一-鿿]` 或 `[一-龥]` 來涵蓋所有常用中文字元。
- **Impact**: 部分中文字元可能不被匹配。
- [ ] 修復

### D-7: search_service 硬編碼模型名稱
- **File**: `backend/tools/search_service.py:315`
- **Severity**: LOW
- **Description**: `os.getenv("MAGIC_MODEL", "gemini-2.5-flash")` 的 fallback 值與其他 service 可能不一致。
- **Impact**: 環境變數未設定時行為可能不如預期。
- [ ] 修復

### D-8: admin.html escapeHtml 重複定義
- **File**: `frontend/admin.html:1118` & `frontend/app.js:56`
- **Severity**: LOW
- **Description**: `escapeHtml()` 在兩個檔案各定義一次，程式碼重複且若其中一個更新另一個未同步會有不一致風險。
- **Impact**: 維護成本增加。
- [ ] 修復

### D-9: index.html script cache busting 手動版號
- **File**: `frontend/index.html:930`
- **Severity**: LOW
- **Description**: `app.js?v=30` 版號寫死，app.js 更新後若忘記改版號，瀏覽器會用到快取的舊版。
- **Impact**: 使用者可能看到過期的前端程式碼。
- [ ] 改用自動化 cache busting

---

## Phase E — Hardcoded Values（寫死的值）

### E-1: .env 含真實 API Key 且可能已進 git history
- **File**: `.env:1-2`
- **Severity**: CRITICAL
- **Hardcoded**: `GEMINI_API_KEY=AIzaSy...`, `TAVILY_API_KEY=tvly-dev-...`
- **Impact**: API key 外洩，任何人可冒用。
- [ ] 從 git history 移除（`git filter-branch` 或 BFG）
- [ ] 立即 rotate 這兩把 key

### E-2: .env 含明文資料庫密碼與內網 IP
- **File**: `.env:7-8, 11, 13`
- **Severity**: CRITICAL
- **Hardcoded**: `DB_PASSWORD=careU1234`, `DB_HOST=192.168.113.128`, 完整 `DATABASE_URL` 含密碼
- **Impact**: 資料庫密碼與內網拓撲暴露。
- [ ] Rotate 密碼
- [ ] 確認 `.env` 在 `.gitignore` 中（不再追蹤）

### E-3: admin.html API_BASE 寫死 localhost
- **File**: `frontend/admin.html:1013`
- **Severity**: CRITICAL
- **Hardcoded**: `const API_BASE = "http://127.0.0.1:8000"`
- **Impact**: 部署後管理後台完全無法使用。
- [ ] 改為 `window.location.origin`
- *（與 A-4 重複，此處標註關聯）*

### E-4: LLM model 名稱寫死在程式碼中
- **File**: `backend/services/llm_service.py:74`
- **Severity**: MEDIUM
- **Hardcoded**: `model_name = "gemini-2.5-flash"` 作為 constructor default
- **Impact**: 換模型需改程式碼才能生效。
- [ ] 改用 `os.getenv("DEFAULT_LLM_MODEL", "gemini-2.5-flash")`

### E-5: Embedding model 與 dimensions 寫死
- **File**: `backend/services/embedding_service.py:25-26`
- **Severity**: MEDIUM
- **Hardcoded**: `self.model = "models/gemini-embedding-2"`, `self.dimensions = 3072`
- **Impact**: 換 embedding model 需改程式碼，且 dimensions 不一致會導致向量搜尋全壞。
- [ ] 改用 env var

### E-6: image_gen model 名稱寫死（3 處）
- **File**: `backend/tools/image_gen.py:53, 96, 132`
- **Severity**: MEDIUM
- **Hardcoded**: `"gemini-flash-lite-latest"`, `"gemini-2.5-flash-image"`
- **Impact**: 模型下架或改名時功能直接壞掉。
- [ ] 改用 env var

### E-7: Background results 常數寫死
- **File**: `backend/main.py:179-180`
- **Severity**: MEDIUM
- **Hardcoded**: `BACKGROUND_RESULTS_MAX = 200`, `BACKGROUND_RESULTS_TTL_SECONDS = 300`
- **Impact**: 無法依部署環境調整，高流量下可能不夠或浪費記憶體。
- [ ] 改用 env var

### E-8: avatars_dir 使用相對路徑
- **File**: `backend/main.py:1843`
- **Severity**: MEDIUM
- **Hardcoded**: `Path("frontend/avatars/personas")` — 相對於 CWD 而非專案根目錄
- **Impact**: 從不同目錄啟動 server 時會找不到 avatar 檔案。
- [ ] 改為 `Path(__file__).parent.parent / "frontend" / "avatars" / "personas"`

### E-9: XTTS circuit breaker 參數寫死
- **File**: `backend/services/tts_service.py:21-22`
- **Severity**: LOW
- **Hardcoded**: `XTTS_FAIL_THRESHOLD = 2`, `XTTS_COOLDOWN_SEC = 90`
- **Impact**: 無法依環境調整熔斷靈敏度。
- [ ] 改用 env var

### E-10: Frontend polling 上限寫死
- **File**: `frontend/app.js:472-473`
- **Severity**: LOW
- **Hardcoded**: 60 次 × 1000ms = 最多等 60 秒
- **Impact**: 慢速環境可能超時，快速環境浪費等待。
- [ ] 抽為可設定常數

### E-11: ADMIN_USERNAME default 為 "admin"
- **File**: `backend/main.py:154`
- **Severity**: LOW
- **Hardcoded**: `os.getenv("ADMIN_USERNAME", "admin")`
- **Impact**: 忘記設定 env var 時用弱預設值。
- [ ] 正式環境應強制設定，未設定時啟動警告

---

## Phase F — README 不一致 / 缺漏

### F-1: Embedding model 名稱寫錯
- **File**: `README.md:169, 581`
- **Severity**: HIGH
- **Description**: README 兩處寫 `text-embedding-004`，但程式碼實際使用 `models/gemini-embedding-2`（`backend/services/embedding_service.py:25`）。
- **Impact**: 讀者對系統理解錯誤；若有人依 README 做相容性開發會用錯模型。
- [ ] 修正為 `gemini-embedding-2`

### F-2: Quick Start DB_PORT 範例與實際 default 不一致
- **File**: `README.md:225`
- **Severity**: HIGH
- **Description**: Quick Start 範例寫 `DB_PORT=5432`，但程式碼 default 是 `5433`（`backend/memory/vector_store.py:24`），`.env.example` 也是 `5433`。環境變數表格（line 274）倒是正確寫 `5433`。
- **Impact**: 使用者照 Quick Start 設 5432，但程式讀 5433，導致 DB 連不上。
- [ ] Quick Start 範例改為 `DB_PORT=5433`

### F-3: Level 3 緊急關鍵字清單嚴重不完整
- **File**: `README.md:53`
- **Severity**: MEDIUM
- **Description**: README 只列「跌倒 / 心臟 / 昏倒」3 個關鍵字，但程式碼實際有 16 個中文 + 10 個英文關鍵字（`backend/agents/i_safe.py:20-29`），包含 `跌落、失去意識、不能動、胸口很痛、胸痛、喘不過氣、呼吸困難、出血、流血、骨折、救命、快叫救護車、站不住` 及英文版。
- **Impact**: 讀者低估系統偵測範圍；安全審查者可能認為覆蓋不足。
- [ ] 補齊完整關鍵字清單或標註「完整清單見 i_safe.py」

### F-4: 趨勢偵測第二條描述不精確
- **File**: `README.md:434`
- **Severity**: LOW
- **Description**: 寫「Three consecutive `comfort`/`urgent` emotions → 長者持續情緒低落」，但條件包含 `urgent`（`i_safe.py:296`）。由於 3 次全 urgent 已被第一條攔截，這條實際抓的是 comfort 混 urgent 的組合，描述應更精確。
- **Impact**: 讀者誤解觸發邏輯。
- [ ] 改為「comfort 與 urgent 混合出現三次」或類似描述

### F-5: XTTS circuit breaker + auto-restart 完全未提及
- **File**: `README.md`（TTS Priority Chain 章節）
- **Severity**: MEDIUM
- **Description**: 程式碼有完整的 XTTS 熔斷機制（連續失敗 2 次 → 冷卻 90 秒，`tts_service.py:17-33`）以及 `scripts/restart_xtts.ps1` 自動重啟腳本，但 README TTS 章節完全沒提到。
- **Impact**: 運維人員不知道 XTTS 會自動熔斷和重啟，排查問題時會困惑。
- [ ] 在 TTS Priority Chain 章節補充 circuit breaker 說明
- [ ] 在環境變數表格補上 `XTTS_RESTART_SCRIPT`

### F-6: iSafe Level 0 safe fast-path 未提及
- **File**: `README.md`（iSafe Implementation Notes 章節）
- **Severity**: LOW
- **Description**: 程式碼有安全詞快速判定 Level 0 的機制（`_SAFE_ZH` + `_SAFE_FAST_PATH_BLOCKERS_ZH`，`i_safe.py:39-56`），可跳過 LLM 呼叫。README 只提了 Level 3 的 fast path。
- **Impact**: 讀者不知道系統有「安全快速通道」，可能認為每則訊息都必經 LLM 分類。
- [ ] 補充 Level 0 fast path 說明

### F-7: L1→L2 auto-escalation 關鍵字清單不完整
- **File**: `README.md:56`
- **Severity**: LOW
- **Description**: README 只列了部分 L2 升級關鍵字，程式碼還有 `沒有力、腳軟、記不住、想不起、忘記藥、沒吃藥、胃口不好、沒有食慾、差點絆、差點滑` 等（`i_safe.py:60-64`）。
- **Impact**: 文件不夠準確，但影響較小。
- [ ] 補齊或標註「完整清單見程式碼」

### F-8: scripts/ 目錄漏列檔案
- **File**: `README.md:186-187`（Project Structure 章節）
- **Severity**: LOW
- **Description**: README 只列了 `streaming_tts_bench.py` 和 `reembed_all.py`，漏掉 `chat_test.py`、`tts_benchmark.py`、`restart_xtts.ps1`。
- **Impact**: 開發者找不到可用的測試 / 維運工具。
- [ ] 補齊 scripts/ 清單

### F-9: Z001 不在預設 ALLOWED_ELDER_IDS 中
- **File**: `README.md:143` vs `.env.example:17`
- **Severity**: MEDIUM
- **Description**: Demo Elders 表格列了 `Z001`，但預設 `ALLOWED_ELDER_IDS=W001,C001,L001` 不含 Z001。使用者照表操作會發現 Z001 無法登入。
- **Impact**: Demo 體驗中斷，使用者困惑。
- [ ] 在 Demo Elders 表格加註「需手動加入 ALLOWED_ELDER_IDS」或將 Z001 加入預設值

### F-10: 環境變數表格缺少 XTTS_RESTART_SCRIPT
- **File**: `README.md`（Environment Variables 章節）
- **Severity**: LOW
- **Description**: `.env.example:34` 定義了 `XTTS_RESTART_SCRIPT`（XTTS 自動重啟腳本路徑），但 README 環境變數表格沒有列出。
- **Impact**: 使用者不知道可以設定自動重啟。
- [ ] 補進環境變數表格

---

## Phase G — 新發現（2026-06-11 第二輪掃描）

### G-1: upload_elder_photo race condition
- **File**: `backend/main.py:1910-1918`
- **Severity**: HIGH
- **Description**: `upload_elder_photo()` 使用 `get_profile()` → 修改 dict → `save_profile()` 模式，不經過 `_mutate_profile()` 的原子 read-modify-write。若同時有另一請求修改同一長者 profile（如 `save_profile`、`add_family_note`），會互相覆蓋變更。對比 `upload_avatar` 使用 `set_persona_field()`（經過 `_mutate_profile`）的做法。
- **Impact**: 並行操作可能導致 profile 欄位遺失。
- [ ] 改用 `_mutate_profile` 或 `update_profile` 只寫入 `photo_path`

### G-2: ~~upload_elder_photo 未驗證長者是否存在~~ ✅ FIXED
- **File**: `backend/main.py:1911`
- **Severity**: MEDIUM
- **Description**: ~~若長者不存在會建立破損 profile~~ 已修復：加入 `if not profile.get("name"): raise HTTPException(404)`。
- [x] 修復

### G-3: 所有上傳 endpoint 缺少檔案大小限制
- **File**: `backend/main.py` — `upload_elder_photo`、`upload_avatar`、`upload_voice`
- **Severity**: MEDIUM
- **Description**: 三個上傳端點都沒有驗證 `UploadFile` 的大小。使用者可以上傳任意大的檔案（數百 MB），耗盡磁碟空間或記憶體。
- **Impact**: DoS 風險，磁碟或記憶體耗盡。
- [ ] 加入檔案大小上限（建議照片 5MB、語音 50MB）

### G-4: 更換長者照片時舊副檔名的檔案未清理
- **File**: `backend/main.py:1905-1921`
- **Severity**: LOW
- **Description**: `photo_filename = f"{elder_id}{suffix}"` — 若先上傳 `W001.jpg` 再上傳 `W001.png`，`os.replace` 只會建立新的 `.png`，舊的 `.jpg` 留在磁碟上成為孤立檔案。
- **Impact**: 磁碟空間逐漸被佔用（量小，但不優雅）。
- [ ] 上傳成功後掃描並刪除同 elder_id 的其他副檔名照片

### G-5: `_SURNAME_INITIAL` dict 重複 key `蔣`
- **File**: `backend/main.py:62, 69`
- **Severity**: LOW
- **Description**: `蔣` 同時出現在 line 62（映射 `"C"`）和 line 69（映射 `"J"`），Python dict 後者覆蓋前者，實際映射為 `"J"`。語言學上兩者皆可（Chiang / Jiang），但 duplicate key 是無意的。
- **Impact**: 姓蔣的長者 ID 會以 `J` 開頭而非 `C`。行為不一定「錯」，但 code 意圖不明確。
- [ ] 移除其中一個（保留符合系統慣例的）

### ~~G-6~~ FALSE POSITIVE — 已移除
- `--palette-ffffff` 定義在 `admin.html:104`，掃描時漏讀。

---

## Summary

| Phase | Severity | Count | Fixed |
|-------|----------|-------|-------|
| A     | Critical | 4     | 0 |
| B     | High     | 12    | 4 (B-1, B-7, B-10, B-11) |
| C     | Medium   | 9     | 1 (C-7) |
| D     | Low      | 9     | 0 |
| E     | Hardcoded Values | 11 | 0 |
| F     | README 不一致/缺漏 | 10 | 0 |
| G     | 新發現（第二輪） | 5 (G-6 false positive 已移除) | 1 (G-2) |
| **Total** | | **60** | **6 fixed, 54 open** |
