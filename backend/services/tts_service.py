import asyncio
import edge_tts
import io

class TTSService:
    
    def __init__(self, voice: str = "zh-TW-HsiaoChenNeural"):
        self.voice = voice
    
    async def _synthesize(self, text: str, emotion: str = "normal") -> bytes:
        """根據情緒調整語調"""
        
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
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._synthesize(text, emotion))
            loop.close()
            return result
        except Exception as e:
            print(f"TTS 錯誤：{e}")
            return b""