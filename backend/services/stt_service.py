import io
import os
import numpy as np
import whisper
import imageio_ffmpeg
os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())

class STTService:
    def __init__(self, model_size: str = "medium", device: str = "cuda"):
        print(f"載入 Whisper 模型：{model_size} on {device}")
        self.model = whisper.load_model(model_size, device=device)
        print("Whisper 模型載入完成！")

        # Breeze ASR 26 台語模型（懶載入）
        self.breeze_model = None
        self.breeze_processor = None
        self.language_mode = "zh"  # "zh" 或 "tai"

    def set_language(self, language: str):
        """切換語言模式：zh（華語）或 tai（台語）"""
        self.language_mode = language
        if language == "tai" and self.breeze_model is None:
            self._load_breeze()
        print(f"STT 語言切換為：{language}")

    def _load_breeze(self):
        try:
            from transformers import WhisperProcessor, WhisperForConditionalGeneration
            import torch
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
            print(f"Breeze ASR 26 載入失敗：{e}")
            import traceback
            traceback.print_exc()
            self.breeze_model = None
            self.language_mode = "zh"

    def _transcribe_breeze(self, audio_bytes: bytes) -> str:
        """用 Breeze ASR 26 辨識台語"""
        try:
            import torch
            import torchaudio

            import tempfile
            import subprocess

            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            print(f"ffmpeg 路徑：{ffmpeg_path}")

            # 先把 webm 存成臨時檔
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp_in:
                tmp_in.write(audio_bytes)
                tmp_in_path = tmp_in.name

            tmp_out_path = tmp_in_path.replace('.webm', '.wav')

            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                subprocess.run([
                    ffmpeg_path, '-y', '-i', tmp_in_path,
                    '-ar', '16000', '-ac', '1', tmp_out_path
                ], capture_output=True, check=True)

                waveform, sample_rate = torchaudio.load(tmp_out_path)
            finally:
                import os
                os.unlink(tmp_in_path)
                if os.path.exists(tmp_out_path):
                    os.unlink(tmp_out_path)

            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0)
            waveform = waveform.squeeze().numpy()

            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(sample_rate, 16000)
                waveform = resampler(torch.tensor(waveform)).numpy()

            inputs = self.breeze_processor(
                waveform,
                sampling_rate=16000,
                return_tensors="pt"
            )

            with torch.no_grad():
                predicted_ids = self.breeze_model.generate(
                    inputs["input_features"]
                )

            text = self.breeze_processor.batch_decode(
                predicted_ids, skip_special_tokens=True
            )[0].strip()

            print(f"Breeze ASR 26 辨識結果：{text}")
            return text

        except Exception as e:
            import traceback
            print(f"Breeze ASR 26 辨識失敗：{e}")
            traceback.print_exc()
            return self._transcribe_whisper(audio_bytes)

    def _transcribe_whisper(self, audio_bytes: bytes) -> str:
        import uuid, subprocess, imageio_ffmpeg
        import soundfile as sf
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"tmp_{uuid.uuid4().hex}")
        webm_path = base + ".webm"
        wav_path = base + ".wav"
        with open(webm_path, 'wb') as f:
            f.write(audio_bytes)
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run([ffmpeg, '-y', '-i', webm_path, '-ar', '16000', '-ac', '1', wav_path],
                        capture_output=True, check=True)
            audio_np, _ = sf.read(wav_path, dtype='float32')
            result = self.model.transcribe(
                audio_np,
                language="zh",
                beam_size=5,
                initial_prompt="這是台灣長者的日常對話，包含親屬稱謂如老伴、孫子、女兒、爺爺、奶奶、阿公、阿嬤，以及台灣常用詞彙如豆漿、象棋、鄧麗君。"
            )
            return result["text"].strip()
        finally:
            for p in [webm_path, wav_path]:
                if os.path.exists(p): os.remove(p)

    def transcribe(self, audio_bytes: bytes) -> str:
        try:
            if self.language_mode == "tai" and self.breeze_model:
                return self._transcribe_breeze(audio_bytes)
            else:
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
                    "duration": 0.0
                }

            import uuid, subprocess, imageio_ffmpeg, numpy as np
            import soundfile as sf, io as _io
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"tmp_{uuid.uuid4().hex}")
            webm_path = base + ".webm"
            wav_path = base + ".wav"
            with open(webm_path, 'wb') as f:
                f.write(audio_bytes)
            try:
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
                subprocess.run([ffmpeg, '-y', '-i', webm_path, '-ar', '16000', '-ac', '1', wav_path],
                               capture_output=True, check=True)
                audio_np, _ = sf.read(wav_path, dtype='float32')
                result = self.model.transcribe(
                    audio_np,
                    language="zh",
                    beam_size=5,
                    initial_prompt="這是台灣長者的日常對話，包含親屬稱謂如老伴、孫子、女兒、爺爺、奶奶、阿公、阿嬤，以及台灣常用詞彙如豆漿、象棋、鄧麗君。",
                    word_timestamps=True
                )
            finally:
                for p in [webm_path, wav_path]:
                    if os.path.exists(p): os.remove(p)
            text = result["text"].strip()
            total_duration = result["segments"][-1]["end"] if result["segments"] else 0.0
            char_count = len(text)
            speech_rate = char_count / total_duration if total_duration > 0 else 0

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
                "duration": round(total_duration, 2)
            }

        except Exception as e:
            import traceback
            print(f"STT 錯誤：{e}")
            traceback.print_exc()
            return {
                "text": "",
                "speech_rate": 0.0,
                "speed_emotion": "normal",
                "duration": 0.0
            }