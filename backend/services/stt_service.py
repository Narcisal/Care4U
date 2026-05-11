import io
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
        try:
            audio_buffer = io.BytesIO(audio_bytes)
            segments, info = self.model.transcribe(
                audio_buffer,
                language="zh",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                initial_prompt="這是台灣長者的日常對話，包含親屬稱謂如老伴、孫子、女兒、爺爺、奶奶、阿公、阿嬤，以及台灣常用詞彙如豆漿、象棋、鄧麗君。"
            )
            text = "".join([seg.text for seg in segments]).strip()
            print(f"STT 辨識結果：{text}")
            return text
        except Exception as e:
            print(f"STT 錯誤：{e}")
            return ""

    def transcribe_with_speed(self, audio_bytes: bytes) -> dict:
        try:
            audio_buffer = io.BytesIO(audio_bytes)
            segments_list = []
            segments, info = self.model.transcribe(
                audio_buffer,
                language="zh",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                initial_prompt="這是台灣長者的日常對話，包含親屬稱謂如老伴、孫子、女兒、爺爺、奶奶、阿公、阿嬤，以及台灣常用詞彙如豆漿、象棋、鄧麗君。",
                word_timestamps=True
            )

            text = ""
            total_duration = 0.0

            for seg in segments:
                text += seg.text
                segments_list.append(seg)
                total_duration = seg.end

            text = text.strip()
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
            print(f"STT 錯誤：{e}")
            return {
                "text": "",
                "speech_rate": 0.0,
                "speed_emotion": "normal",
                "duration": 0.0
            }