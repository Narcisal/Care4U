import asyncio
import edge_tts
import io
import os
import requests

BREEZYVOICE_URL = os.getenv("BREEZYVOICE_URL", "http://localhost:8080")
LUXTTS_URL = os.getenv("LUXTTS_URL", "http://localhost:8081")
XTTS_URL = os.getenv("XTTS_URL", "http://localhost:8082")

class TTSService:

    def __init__(self, voice: str = "zh-TW-HsiaoChenNeural"):
        self.voice = voice
        self.engine = "breezyvoice"
        self.voice_path = None      # BreezyVoice 聲音樣本路徑
        self.persona_prompt = None  # 人格提示

    def set_engine(self, engine: str, voice_path: str = None):
        """
        切換 TTS 引擎
        engine: "edge" | "breezyvoice"
        voice_path: BreezyVoice 聲音樣本路徑
        """
        self.engine = engine
        self.voice_path = voice_path
        print(f"TTS 引擎切換為：{engine}, 聲音樣本：{voice_path}")

    def reset_engine(self):
        """重置為預設 edge-tts"""
        self.engine = "edge"
        self.voice_path = None
        print("TTS 引擎重置為：edge")

    def _breezyvoice_synthesize(self, text: str) -> bytes:
        """用 BreezyVoice 生成語音（聲音克隆）"""
        try:
            payload = {
                "model": "tts-1",
                "voice": "shimmer",
                "input": text,
                "speed": 1.0
            }
            res = requests.post(
                f"{BREEZYVOICE_URL}/v1/audio/speech",
                json=payload,
                timeout=60
            )
            if res.status_code == 200:
                print(f"BreezyVoice 生成成功，長度：{len(res.content)} bytes")
                return res.content
            else:
                print(f"BreezyVoice 失敗：{res.status_code} {res.text}")
                return b""
        except Exception as e:
            print(f"BreezyVoice 錯誤：{e}")
            return b""

    async def _edge_synthesize(self, text: str,
                                emotion: str = "normal") -> bytes:
        """用 Edge TTS 生成語音"""
        if emotion == "happy":
            rate, pitch, volume = "+20%", "+10Hz", "+5%"
        elif emotion == "comfort":
            rate, pitch, volume = "-20%", "-5Hz", "-5%"
        elif emotion == "urgent":
            rate, pitch, volume = "+15%", "+8Hz", "+15%"
        elif emotion == "remind":
            rate, pitch, volume = "-8%", "+2Hz", "+0%"
        else:
            rate, pitch, volume = "+0%", "+0Hz", "+0%"

        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=rate,
            pitch=pitch,
            volume=volume
        )

        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])

        return audio_buffer.getvalue()

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

            # 預設 edge-tts
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self._edge_synthesize(text, emotion)
            )
            loop.close()
            return result

        except Exception as e:
            print(f"TTS 錯誤：{e}")
            return b""
    
    def _luxtts_synthesize(self, text: str) -> bytes:
        """用 LuxTTS 生成語音（聲音克隆）"""
        try:
            payload = {
                "text": text,
                "voice_path": self.voice_path,
                "speed": 1.0
            }
            res = requests.post(
                f"{LUXTTS_URL}/v1/audio/speech",
                json=payload,
                timeout=30
            )
            if res.status_code == 200:
                print(f"LuxTTS 生成成功，長度：{len(res.content)} bytes")
                return res.content
            else:
                print(f"LuxTTS 失敗：{res.status_code} {res.text}")
                return b""
        except Exception as e:
            print(f"LuxTTS 錯誤：{e}")
            return b""
        
    def _xtts_synthesize(self, text: str) -> bytes:
        """用 XTTS v2 生成語音（聲音克隆）"""
        try:
            payload = {
                "text": text,
                "voice_path": self.voice_path,
                "language": "zh-cn",
                "speed": 1.0
            }
            res = requests.post(
                f"{XTTS_URL}/v1/audio/speech",
                json=payload,
                timeout=30
            )
            if res.status_code == 200:
                print(f"XTTS 生成成功，長度：{len(res.content)} bytes")
                return res.content
            else:
                print(f"XTTS 失敗：{res.status_code} {res.text}")
                return b""
        except Exception as e:
            print(f"XTTS 錯誤：{e}")
            return b""