import asyncio
import edge_tts
import io
import os
import requests

BREEZYVOICE_URL = os.getenv("BREEZYVOICE_URL", "http://localhost:8080")
LUXTTS_URL = os.getenv("LUXTTS_URL", "http://localhost:8081")
XTTS_URL = os.getenv("XTTS_URL", "http://localhost:8082")

# (rate, pitch, volume) per emotion — extend here to add new emotions
EMOTION_PROSODY: dict[str, tuple[str, str, str]] = {
    "happy":   ("+20%", "+10Hz", "+5%"),
    "comfort": ("-20%", "-5Hz",  "-5%"),
    "urgent":  ("+15%", "+8Hz",  "+15%"),
    "remind":  ("-8%",  "+2Hz",  "+0%"),
    "normal":  ("+0%",  "+0Hz",  "+0%"),
}


class TTSService:

    def __init__(self, voice: str = "zh-TW-HsiaoChenNeural"):
        self.voice = voice
        self.engine = "edge"        # safe default; set_engine() switches to a cloning engine
        self.voice_path = None

    def set_engine(self, engine: str, voice_path: str = None):
        """Switch TTS engine. engine: "edge" | "breezyvoice" | "luxtts" | "xtts" """
        self.engine = engine
        self.voice_path = voice_path
        print(f"TTS 引擎切換為：{engine}, 聲音樣本：{voice_path}")

    def reset_engine(self):
        """Reset to default edge-tts."""
        self.engine = "edge"
        self.voice_path = None
        print("TTS 引擎重置為：edge")

    # ------------------------------------------------------------------
    # Voice-cloning back-ends
    # ------------------------------------------------------------------

    def _breezyvoice_synthesize(self, text: str) -> bytes:
        """Generate speech via BreezyVoice voice-cloning server."""
        try:
            payload = {
                "model": "tts-1",
                "voice": "shimmer",
                "input": text,
                "speed": 1.0,
            }
            res = requests.post(
                f"{BREEZYVOICE_URL}/v1/audio/speech",
                json=payload,
                timeout=60,
            )
            if res.status_code == 200:
                print(f"BreezyVoice 生成成功，長度：{len(res.content)} bytes")
                return res.content
            print(f"BreezyVoice 失敗：{res.status_code} {res.text}")
            return b""
        except Exception as e:
            print(f"BreezyVoice 錯誤：{e}")
            return b""

    def _luxtts_synthesize(self, text: str) -> bytes:
        """Generate speech via LuxTTS voice-cloning server."""
        try:
            payload = {
                "text": text,
                "voice_path": self.voice_path,
                "speed": 1.0,
            }
            res = requests.post(
                f"{LUXTTS_URL}/v1/audio/speech",
                json=payload,
                timeout=30,
            )
            if res.status_code == 200:
                print(f"LuxTTS 生成成功，長度：{len(res.content)} bytes")
                return res.content
            print(f"LuxTTS 失敗：{res.status_code} {res.text}")
            return b""
        except Exception as e:
            print(f"LuxTTS 錯誤：{e}")
            return b""

    def _xtts_synthesize(self, text: str) -> bytes:
        """Generate speech via XTTS v2 voice-cloning server."""
        try:
            payload = {
                "text": text,
                "voice_path": self.voice_path,
                "language": "zh-cn",
                "speed": 1.0,
            }
            res = requests.post(
                f"{XTTS_URL}/v1/audio/speech",
                json=payload,
                timeout=30,
            )
            if res.status_code == 200:
                print(f"XTTS 生成成功，長度：{len(res.content)} bytes")
                return res.content
            print(f"XTTS 失敗：{res.status_code} {res.text}")
            return b""
        except Exception as e:
            print(f"XTTS 錯誤：{e}")
            return b""

    # ------------------------------------------------------------------
    # Edge-TTS (emotion-aware fallback)
    # ------------------------------------------------------------------

    async def _edge_synthesize(self, text: str, emotion: str = "normal") -> bytes:
        """Generate speech via Edge-TTS with emotion-adjusted prosody."""
        rate, pitch, volume = EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["normal"])

        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=rate,
            pitch=pitch,
            volume=volume,
        )

        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])

        return audio_buffer.getvalue()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(self, text: str, emotion: str = "normal") -> bytes:
        try:
            if self.engine == "breezyvoice":
                result = self._breezyvoice_synthesize(text)
                if result:
                    return result
                print("BreezyVoice 失敗，降級到 edge-tts")
            elif self.engine == "xtts":
                result = self._xtts_synthesize(text)
                if result:
                    return result
                print("XTTS 失敗，降級到 edge-tts")
            elif self.engine == "luxtts":
                result = self._luxtts_synthesize(text)
                if result:
                    return result
                print("LuxTTS 失敗，降級到 edge-tts")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._edge_synthesize(text, emotion))
            loop.close()
            return result

        except Exception as e:
            print(f"TTS 錯誤：{e}")
            return b""
