import io
import wave
import numpy as np
from faster_whisper import WhisperModel

class STTService:
    
    def __init__(self, model_size: str = "medium", device: str = "cpu"):
        print(f"載入 Whisper 模型：{model_size} on {device}")
        self.model = WhisperModel(
            model_size, 
            device=device,
            compute_type="float16" if device == "cuda" else "int8"
        )
        print("Whisper 模型載入完成！")
    
    def transcribe(self, audio_bytes: bytes) -> str:
        """將音訊 bytes 轉成文字"""
        try:
            audio_buffer = io.BytesIO(audio_bytes)
            segments, info = self.model.transcribe(
                audio_buffer,
                language="zh",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            text = "".join([seg.text for seg in segments]).strip()
            print(f"STT 辨識結果：{text}")
            return text
            
        except Exception as e:
            print(f"STT 錯誤：{e}")
            return ""