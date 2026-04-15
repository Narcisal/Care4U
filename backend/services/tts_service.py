import asyncio
import edge_tts
import io

class TTSService:
    
    def __init__(self, voice: str = "zh-TW-HsiaoChenNeural"):
        # 可選語音：
        # zh-TW-HsiaoChenNeural（女聲，年輕）
        # zh-TW-YunJheNeural（男聲）
        # zh-TW-HsiaoYuNeural（女聲，活潑）
        self.voice = voice
    
    async def _synthesize(self, text: str) -> bytes:
        """將文字轉成音訊 bytes"""
        communicate = edge_tts.Communicate(text, self.voice)
        audio_buffer = io.BytesIO()
        
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        
        return audio_buffer.getvalue()
    
    def synthesize(self, text: str) -> bytes:
        """同步版本的 TTS"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._synthesize(text))
            loop.close()
            return result
        except Exception as e:
            print(f"TTS 錯誤：{e}")
            return b""