import io
import importlib.util
import os
import subprocess
import tempfile
import traceback
import uuid
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np

os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())

_WHISPER_PROMPT = (
    "這是台灣長者的日常對話，包含親屬稱謂如老伴、孫子、女兒、爺爺、奶奶、阿公、阿嬤，"
    "以及台灣常用詞彙如豆漿、象棋、鄧麗君。"
)


def get_stt_environment_status() -> dict:
    """Return dependency/cache readiness without loading heavy STT models."""
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    breeze_cache = hf_cache / "models--MediaTek-Research--Breeze-ASR-26"
    return {
        "whisper_available": importlib.util.find_spec("whisper") is not None,
        "torch_available": importlib.util.find_spec("torch") is not None,
        "torchaudio_available": importlib.util.find_spec("torchaudio") is not None,
        "transformers_available": importlib.util.find_spec("transformers") is not None,
        "soundfile_available": importlib.util.find_spec("soundfile") is not None,
        "breeze_cache_exists": breeze_cache.exists(),
        "breeze_cache_path": str(breeze_cache),
        "ffmpeg_path": imageio_ffmpeg.get_ffmpeg_exe(),
    }


class STTService:
    def __init__(self, model_size: str = "medium", device: str = "cuda"):
        self.model = None
        self.whisper_error = None
        self.breeze_model = None
        self.breeze_processor = None
        self.breeze_error = None
        self.language_mode = "zh"   # "zh" | "tai"
        self._load_whisper(model_size, device)

    def _load_whisper(self, model_size: str, device: str):
        try:
            import whisper
            print(f"載入 Whisper 模型：{model_size} on {device}")
            self.model = whisper.load_model(model_size, device=device)
            print("Whisper 模型載入完成！")
        except Exception as e:
            self.model = None
            self.whisper_error = str(e)
            print(f"Whisper 載入失敗：{e}")

    # ------------------------------------------------------------------
    # Language switching
    # ------------------------------------------------------------------

    def set_language(self, language: str):
        """Switch recognition language: 'zh' (Mandarin) or 'tai' (Taiwanese)."""
        self.language_mode = language
        if language == "tai" and self.breeze_model is None:
            self._load_breeze()
        print(f"STT 語言切換為：{language}")

    def _load_breeze(self):
        try:
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
            print("載入 Breeze ASR 26 台語模型...")
            self.breeze_processor = WhisperProcessor.from_pretrained(
                "MediaTek-Research/Breeze-ASR-26"
            )
            self.breeze_model = WhisperForConditionalGeneration.from_pretrained(
                "MediaTek-Research/Breeze-ASR-26"
            )
            self.breeze_model.eval()
            print(f"Breeze ASR 26 載入完成！model={self.breeze_model is not None}")
        except Exception as e:
            self.breeze_error = str(e)
            print(f"Breeze ASR 26 載入失敗：{e}")
            traceback.print_exc()
            self.breeze_model = None

    # ------------------------------------------------------------------
    # Shared audio conversion helper
    # ------------------------------------------------------------------

    def _read_wav_float32(self, wav_path: str) -> tuple[np.ndarray, int]:
        """Read mono/stereo wav as float32 without requiring soundfile."""
        try:
            import soundfile as sf
            audio_np, sample_rate = sf.read(wav_path, dtype="float32")
            return audio_np, sample_rate
        except Exception:
            with wave.open(wav_path, "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_rate = wav_file.getframerate()
                sample_width = wav_file.getsampwidth()
                frames = wav_file.readframes(wav_file.getnframes())

            if sample_width == 2:
                audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                audio = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
                audio = (audio - 128.0) / 128.0

            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1)
            return audio, sample_rate

    def _convert_to_numpy(self, audio_bytes: bytes) -> np.ndarray:
        """Convert raw webm audio bytes → 16 kHz mono float32 numpy array.

        Uses a pair of temp files so ffmpeg can work on disk (not all
        codecs support piped input).  Files are always cleaned up.
        """
        base = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"tmp_{uuid.uuid4().hex}",
        )
        webm_path = base + ".webm"
        wav_path = base + ".wav"
        with open(webm_path, "wb") as f:
            f.write(audio_bytes)
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run(
                [ffmpeg, "-y", "-i", webm_path, "-ar", "16000", "-ac", "1", wav_path],
                capture_output=True,
                check=True,
            )
            audio_np, _ = self._read_wav_float32(wav_path)
            return audio_np
        finally:
            for p in (webm_path, wav_path):
                if os.path.exists(p):
                    os.remove(p)

    # ------------------------------------------------------------------
    # Transcription back-ends
    # ------------------------------------------------------------------

    def _transcribe_whisper(self, audio_bytes: bytes) -> str:
        if not self.model:
            print(f"Whisper 尚未可用：{self.whisper_error or '未載入'}")
            return ""
        audio_np = self._convert_to_numpy(audio_bytes)
        result = self.model.transcribe(
            audio_np,
            language="zh",
            beam_size=5,
            initial_prompt=_WHISPER_PROMPT,
        )
        return result["text"].strip()

    def _transcribe_whisper_with_timestamps(self, audio_bytes: bytes) -> dict:
        """Return full Whisper result dict (includes word_timestamps segments)."""
        if not self.model:
            print(f"Whisper 尚未可用：{self.whisper_error or '未載入'}")
            return {"text": "", "segments": []}
        audio_np = self._convert_to_numpy(audio_bytes)
        return self.model.transcribe(
            audio_np,
            language="zh",
            beam_size=5,
            initial_prompt=_WHISPER_PROMPT,
            word_timestamps=True,
        )

    def _transcribe_breeze(self, audio_bytes: bytes) -> str:
        """Transcribe Taiwanese using Breeze ASR 26; falls back to Whisper on error."""
        try:
            import torch

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
                tmp_in.write(audio_bytes)
                tmp_in_path = tmp_in.name
            tmp_out_path = tmp_in_path.replace(".webm", ".wav")

            try:
                subprocess.run(
                    [ffmpeg_path, "-y", "-i", tmp_in_path, "-ar", "16000", "-ac", "1", tmp_out_path],
                    capture_output=True,
                    check=True,
                )
                waveform, sample_rate = self._read_wav_float32(tmp_out_path)
            finally:
                os.unlink(tmp_in_path)
                if os.path.exists(tmp_out_path):
                    os.unlink(tmp_out_path)

            if getattr(waveform, "ndim", 1) > 1:
                waveform = waveform.mean(axis=1)

            inputs = self.breeze_processor(
                waveform,
                sampling_rate=16000,
                return_tensors="pt",
            )
            with torch.no_grad():
                predicted_ids = self.breeze_model.generate(inputs["input_features"])

            text = self.breeze_processor.batch_decode(
                predicted_ids, skip_special_tokens=True
            )[0].strip()
            print(f"Breeze ASR 26 辨識結果：{text}")
            return text

        except Exception as e:
            print(f"Breeze ASR 26 辨識失敗：{e}")
            traceback.print_exc()
            if not self.model:
                raise RuntimeError(
                    "Breeze ASR 辨識失敗，且 Whisper 未載入"
                ) from e
            return self._transcribe_whisper(audio_bytes)

    def status(self) -> dict:
        env = get_stt_environment_status()
        env.update({
            "language_mode": self.language_mode,
            "whisper_loaded": self.model is not None,
            "whisper_error": self.whisper_error,
            "breeze_loaded": self.breeze_model is not None,
            "breeze_error": self.breeze_error,
        })
        return env

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(self, audio_bytes: bytes) -> str:
        try:
            if self.language_mode == "tai" and self.breeze_model:
                return self._transcribe_breeze(audio_bytes)
            text = self._transcribe_whisper(audio_bytes)
            print(f"STT 辨識結果：{text}")
            return text
        except Exception as e:
            print(f"STT 錯誤：{e}")
            return ""

    def transcribe_with_speed(self, audio_bytes: bytes) -> dict:
        print(f"STT 模式：{self.language_mode}, breeze_model={self.breeze_model is not None}")
        try:
            if self.language_mode == "tai" and self.breeze_model:
                text = self._transcribe_breeze(audio_bytes)
                return {
                    "text": text,
                    "speech_rate": 0.0,
                    "speed_emotion": "normal",
                    "duration": 0.0,
                }

            if not self.model:
                return {
                    "text": "",
                    "speech_rate": 0.0,
                    "speed_emotion": "normal",
                    "duration": 0.0,
                    "error": self.whisper_error or "Whisper model 未載入",
                }

            result = self._transcribe_whisper_with_timestamps(audio_bytes)
            text = result["text"].strip()
            total_duration = result["segments"][-1]["end"] if result["segments"] else 0.0
            speech_rate = len(text) / total_duration if total_duration > 0 else 0.0

            if speech_rate > 5.0:
                speed_emotion = "fast"
            elif speech_rate < 2.0:
                speed_emotion = "slow"
            else:
                speed_emotion = "normal"

            print(f"STT 辨識結果：{text}")
            print(f"語速：{speech_rate:.1f} 字/秒，判定：{speed_emotion}")

            return {
                "text": text,
                "speech_rate": round(speech_rate, 2),
                "speed_emotion": speed_emotion,
                "duration": round(total_duration, 2),
            }

        except Exception as e:
            print(f"STT 錯誤：{e}")
            traceback.print_exc()
            return {
                "text": "",
                "speech_rate": 0.0,
                "speed_emotion": "normal",
                "duration": 0.0,
                "error": str(e),
            }
