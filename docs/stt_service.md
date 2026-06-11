# STT Service

語音辨識服務，支援國語（Whisper）和台語（Breeze ASR）。

**檔案**：`backend/services/stt_service.py`

---

## 依賴關係

| 呼叫誰 | 被誰呼叫 |
|---------|---------|
| OpenAI Whisper（本地模型） | `main.py` 的 `/api/stt` |
| MediaTek Breeze ASR 26（本地模型） | — |
| ffmpeg（透過 `imageio_ffmpeg`） | — |

---

## Worker Pool（在 main.py 中管理）

```python
# main.py
STT_POOL_SIZE = int(os.getenv("STT_POOL_SIZE", "1"))
stt_pool: list[STTService] = []
stt_pool_lock: asyncio.Queue = asyncio.Queue()
```

- Startup 時建立 `STT_POOL_SIZE` 個 STTService instance
- 透過 `asyncio.Queue` 實現借還：`await stt_pool_lock.get()` 借，`stt_pool_lock.put()` 還
- 每個 worker 佔約 5 GB VRAM（Whisper medium）

**CUDA 失敗降級**：初始化 CUDA 失敗 → 自動重建為 CPU workers。

---

## Instance 狀態

| 屬性 | 說明 |
|------|------|
| `model` | Whisper 模型 instance，None 表示載入失敗 |
| `whisper_error` | 載入失敗的錯誤訊息 |
| `breeze_model` | Breeze ASR 模型，None 表示未載入或失敗 |
| `breeze_processor` | Breeze 的 WhisperProcessor |
| `breeze_error` | 載入失敗的錯誤訊息 |
| `language_mode` | `"zh"` 或 `"tai"`，預設 `"zh"` |

---

## Public API

### `__init__(model_size="medium", device="cuda")`

立即載入 Whisper 模型。失敗時 `self.model = None`，不 raise。

### `set_language(language: str)`

切換語言模式。`"tai"` 時若 Breeze 尚未載入，觸發 `_load_breeze()`（延遲載入）。

### `transcribe(audio_bytes) → str`

基本辨識，回傳純文字。

```
language_mode == "tai" 且 breeze_model 可用?
├─ YES → _transcribe_breeze(audio_bytes)
└─ NO  → _transcribe_whisper(audio_bytes)
```

### `transcribe_with_speed(audio_bytes) → dict`

辨識 + 語速分析。

```python
{
    "text": str,            # 辨識文字
    "speech_rate": float,   # 字/秒
    "speed_emotion": str,   # "fast" | "slow" | "normal"
    "duration": float,      # 音訊秒數
}
```

**語速判定閾值**：

| speech_rate | speed_emotion |
|-------------|--------------|
| > 5.0 字/秒 | "fast" |
| < 2.0 字/秒 | "slow" |
| 2.0 - 5.0 | "normal" |

台語模式不支援語速分析（`speech_rate = 0.0, speed_emotion = "normal"`），因為 Breeze 不提供 word_timestamps。

### `status() → dict`

回傳環境狀態（dependency 是否安裝、模型是否載入、cache 路徑等）。

---

## Internal Methods

### `_convert_to_numpy(audio_bytes) → np.ndarray`

webm → 16kHz mono float32 numpy array。

1. 寫入 temp `.webm` 檔
2. ffmpeg 轉換為 `.wav`（`-ar 16000 -ac 1`）
3. `_read_wav_float32()` 讀取
4. 清理 temp 檔

### `_read_wav_float32(wav_path) → (np.ndarray, int)`

優先用 `soundfile`，失敗時退回 `wave` 模組手動解析。支援 8/16/32 bit，自動轉 mono。

### `_transcribe_whisper(audio_bytes) → str`

```python
self.model.transcribe(
    audio_np,
    language="zh",
    beam_size=5,
    initial_prompt=_WHISPER_PROMPT,
)
```

`_WHISPER_PROMPT` 引導辨識台灣長者常用詞彙（親屬稱謂、日常用語）。

### `_transcribe_whisper_with_timestamps(audio_bytes) → dict`

同上但 `word_timestamps=True`，回傳包含 `segments` 的完整結果 dict。用於語速計算。

### `_transcribe_breeze(audio_bytes) → str`

1. ffmpeg 轉換 webm → wav（16kHz mono）
2. Breeze processor → input_features
3. `model.generate()` → predicted_ids
4. `batch_decode()` → text
5. **失敗降級**：Breeze 辨識失敗 → 嘗試 Whisper；Whisper 也不可用 → raise

---

## Gotchas

1. **ffmpeg 路徑注入 PATH**：`os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())`，在 module import 時就執行，影響整個 process 的 PATH。
2. **temp 檔案路徑在 `backend/services/` 目錄下**：`_convert_to_numpy` 使用 `os.path.dirname(os.path.abspath(__file__))` 作為基底，temp 檔案會出現在 source code 目錄中，不在 system temp dir。
3. **Breeze 延遲載入約需 30-60 秒**：首次切換到台語時，使用者會感受到明顯延遲（需下載 + 載入模型）。
4. **Whisper 的 `initial_prompt` 不是硬約束**：它是 decoder 的引導文本，可以提高特定詞彙的辨識率，但不保證結果一定包含這些詞。
5. **`transcribe_with_speed` 的 duration 取 `segments[-1]["end"]`**：如果最後一個 segment 之後有靜音，duration 可能偏小。
