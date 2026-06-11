# TTS Service

語音合成服務，4 層 fallback chain。

**檔案**：`backend/services/tts_service.py`

---

## 依賴關係

| 呼叫誰 | 被誰呼叫 |
|---------|---------|
| XTTS v2 HTTP API | `main.py` 的 `/api/tts` |
| LuxTTS HTTP API | `Decision._setup_persona()` 設定引擎 |
| BreezyVoice HTTP API | — |
| edge-tts（雲端） | — |
| Windows SAPI（本地 OS） | — |

---

## Module-level 全域狀態

### XTTS Circuit Breaker

所有 TTSService instance **共享**斷路器狀態：

| 變數 | 說明 |
|------|------|
| `_xtts_lock` | `threading.Lock` |
| `_xtts_fail_count` | 連續失敗次數 |
| `_xtts_broken_until` | `time.time()` 基準的冷卻結束時間 |
| `_xtts_restarting` | `bool`，重啟過程中為 True，跳過 XTTS 請求 |
| `XTTS_FAIL_THRESHOLD` | 2（連續失敗 2 次觸發） |
| `XTTS_COOLDOWN_SEC` | 120 秒 |
| `XTTS_MAX_CHARS` | 40（超過此長度的文字會被截斷，避免 XTTS tokenizer OOB crash） |

**觸發流程**：

```
XTTS 請求失敗
└─ _record_xtts_failure()
   ├─ _xtts_fail_count += 1
   └─ count ≥ THRESHOLD?
      ├─ YES → _xtts_broken_until = now + 120s
      │        _xtts_fail_count = 0（重設）
      │        _trigger_xtts_restart()
      └─ NO → return b""
```

**自動重啟**：若 `XTTS_RESTART_SCRIPT` 環境變數有值，在 daemon thread 中執行 PowerShell 腳本。重啟流程包含 health probe（GET 請求，最多 20 次 × 5 秒間隔），確認 XTTS 重新上線後才清除冷卻狀態。

**冷卻檢查**：`_xtts_synthesize()` 開頭檢查 `_xtts_broken_until` 和 `_xtts_restarting`，任一為 True 直接 return `b""`。

### 情緒語調

```python
EMOTION_PROSODY = {
    "happy":   ("+20%", "+10Hz", "+5%"),    # rate, pitch, volume
    "comfort": ("-20%", "-5Hz",  "-5%"),
    "urgent":  ("+15%", "+8Hz",  "+15%"),
    "remind":  ("-8%",  "+2Hz",  "+0%"),
    "normal":  ("+0%",  "+0Hz",  "+0%"),
}
```

只有 edge-tts 使用這些參數。XTTS / LuxTTS / BreezyVoice 不支援語調控制。

---

## Public API

### `__init__(voice="zh-TW-HsiaoChenNeural")`

- `voice`：edge-tts 的聲音 ID
- `engine`：預設 `"xtts"`
- `voice_path`：聲音樣本路徑（XTTS / LuxTTS 用）

### `set_engine(engine, voice_path=None)`

切換引擎。`normalize_engine()` 驗證引擎名稱，不認識的一律降為 `"edge"`。

### `synthesize(text, emotion="normal") → bytes`

回傳 WAV/MP3 音訊 bytes。`b""` 表示完全失敗。

**Fallback chain**：

```
engine == "breezyvoice"?
├─ _breezyvoice_synthesize(text) → 有結果 return
├─ 失敗 → fall through

engine == "xtts"?
├─ _xtts_synthesize(text) → 有結果 return
├─ 失敗（含 circuit breaker） → fall through

engine == "luxtts"?
├─ _luxtts_synthesize(text) → 有結果 return
├─ 失敗 → fall through

_edge_synthesize(text, emotion) → 有結果 return
├─ 失敗 → fall through

_windows_sapi_synthesize(text) → return（最終保底）
```

---

## 各引擎實作細節

### XTTS v2（`_xtts_synthesize`）

- URL：`XTTS_URL/v1/audio/speech`（預設 `http://localhost:8082`）
- Payload：`{text, voice_path, language: "zh-cn", speed: 1.0}`
- Timeout：30 秒
- 文字前處理：`_strip_emoji()` 移除 emoji，截斷超過 `XTTS_MAX_CHARS`（40）的文字
- WAV 驗證：`_is_valid_wav()` 檢查回應是否為有效 WAV（RIFF header），無效視為失敗
- 成功：重設 `_xtts_fail_count = 0`
- 失敗（含 500 狀態碼）：直接觸發 `_record_xtts_failure()` + 重啟
- 無 voice_path → 直接 return `b""`（不嘗試，因為 XTTS 需要聲音樣本）

### LuxTTS（`_luxtts_synthesize`）

- URL：`LUXTTS_URL/v1/audio/speech`（預設 `http://localhost:8081`）
- Payload：`{text, voice_path, speed: 1.0}`
- Timeout：30 秒
- 沒有 circuit breaker

### BreezyVoice（`_breezyvoice_synthesize`）

- URL：`BREEZYVOICE_URL/v1/audio/speech`（預設 `http://localhost:8080`）
- Payload：`{model: "tts-1", voice: "shimmer", input: text, speed: 1.0}`
- Timeout：60 秒（最長，因為 voice cloning 較慢）

### edge-tts（`_edge_synthesize`）

- async 方法，透過 `asyncio.new_event_loop()` 在 sync context 中執行
- 使用 `EMOTION_PROSODY` 調整語速/音高/音量
- 聲音：`zh-TW-HsiaoChenNeural`

### Windows SAPI（`_windows_sapi_synthesize`）

- 只在 `os.name == "nt"` 時可用
- 透過 PowerShell 呼叫 `System.Speech.Synthesis.SpeechSynthesizer`
- 先寫入 tempfile `.wav` 再讀回
- 不支援情緒語調
- Timeout：30 秒

---

## Gotchas

1. **edge-tts 的 event loop 每次都新建**：`asyncio.new_event_loop()` + `loop.close()`。在高併發下可能有效能問題，但因為 edge-tts 是 fallback 而非主要引擎，實際影響有限。
2. **XTTS circuit breaker 的 `_xtts_fail_count` 在觸發後重設為 0**：所以冷卻結束後只需再失敗 2 次就會再次觸發。
3. **BreezyVoice 的 voice 參數是硬編碼的 `"shimmer"`**：不使用 `self.voice_path`。這可能不是預期行為。
4. **Windows SAPI 的 text 直接嵌入 PowerShell 腳本**：透過 JSON serialize + `ConvertFrom-Json` 處理，但極端情況下（含特殊字元）可能有 injection 風險。目前用 `json.dumps` + base64 encoded command 緩解。
5. **`synthesize()` 的 emotion 參數只對 edge-tts 有效**：其他引擎忽略 emotion。
6. **XTTS tokenizer OOB crash**：某些中文字元會導致 XTTS 的 tokenizer 產生超出範圍的 token ID，觸發 CUDA `srcIndex < srcSelectDimSize` assertion failure。`XTTS_MAX_CHARS=40` 是緩解措施，非根本修復。
7. **三層 emoji 防禦**：LLM prompt 指示不使用 emoji → `_strip_emoji()` 在 TTS 前移除 → 前端 `stripEmoji()` 最終清理。XTTS tokenizer 無法處理 emoji 字元。
8. **XTTS GPU 請求序列化**：`api.py` 中使用 `threading.Lock()` 確保同時只有一個推理請求，避免 tensor dimension mismatch。
