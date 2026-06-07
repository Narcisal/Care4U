import asyncio
import base64
import edge_tts
import io
import json
import os
import requests
import subprocess
import tempfile

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
    SUPPORTED_ENGINES = {"edge", "breezyvoice", "luxtts", "xtts"}

    def __init__(self, voice: str = "zh-TW-HsiaoChenNeural"):
        self.voice = voice
        self.engine = "xtts"
        self.voice_path = None

    def set_engine(self, engine: str, voice_path: str = None):
        """Switch TTS engine. engine: "edge" | "breezyvoice" | "luxtts" | "xtts" """
        normalized = self.normalize_engine(engine)
        self.engine = normalized
        self.voice_path = voice_path if normalized != "edge" else None
        print(f"TTS 引擎切換為：{normalized}, 聲音樣本：{self.voice_path}")

    @classmethod
    def normalize_engine(cls, engine: str | None) -> str:
        normalized = (engine or "").strip().lower()
        return normalized if normalized in cls.SUPPORTED_ENGINES else "edge"

    def reset_engine(self):
        """Reset to default edge-tts."""
        self.engine = "edge"
        self.voice_path = None
        print("TTS 引擎重置為：edge")

    def use_edge_fallback(self):
        self.engine = "edge"
        self.voice_path = None

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
        if not self.voice_path:
            print("XTTS 未設定聲音樣本，降級到 edge-tts")
            return b""
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

    def _windows_sapi_synthesize(self, text: str) -> bytes:
        """Last-resort offline fallback for Windows demo environments."""
        if os.name != "nt":
            return b""

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            payload = json.dumps({"text": text, "path": tmp_path}, ensure_ascii=False)
            script = f"""
$payload = @'
{payload}
'@ | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.SetOutputToWaveFile($payload.path)
$speaker.Speak($payload.text)
$speaker.Dispose()
"""
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    encoded,
                ],
                capture_output=True,
                timeout=30,
            )
            if completed.returncode != 0:
                print(f"Windows SAPI 失敗：{completed.stderr.decode(errors='ignore')}")
                return b""

            with open(tmp_path, "rb") as f:
                return f.read()
        except Exception as e:
            print(f"Windows SAPI 錯誤：{e}")
            return b""
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

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

            result = b""
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._edge_synthesize(text, emotion))
            except Exception as e:
                print(f"edge-tts 錯誤：{e}")
            finally:
                loop.close()

            if result:
                return result

            print("edge-tts 失敗，改用 Windows SAPI 離線備援")
            return self._windows_sapi_synthesize(text)

        except Exception as e:
            print(f"TTS 錯誤：{e}")
            return self._windows_sapi_synthesize(text)
