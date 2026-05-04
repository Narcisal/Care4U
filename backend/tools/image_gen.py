import os
import base64
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 觸發懷舊圖片的關鍵字
NOSTALGIC_KEYWORDS = [
    "懷念", "以前", "年輕時", "小時候", "那時候", "記得",
    "從前", "過去", "當年", "老家", "故鄉"
]

# 觸發夢境視覺化的關鍵字
DREAM_KEYWORDS = [
    "夢", "夢到", "夢見", "昨晚夢", "做夢"
]

def detect_image_trigger(message: str) -> str:
    """
    偵測訊息是否需要生成圖片
    回傳：'nostalgic' | 'dream' | None
    """
    if any(kw in message for kw in DREAM_KEYWORDS):
        return "dream"
    if any(kw in message for kw in NOSTALGIC_KEYWORDS):
        return "nostalgic"
    return None

def generate_image(message: str, trigger_type: str) -> str | None:
    """
    根據長者說的話生成圖片
    回傳 base64 編碼的圖片字串，失敗回傳 None
    """
    try:
        if trigger_type == "dream":
            prompt = f"""
            根據以下夢境描述，生成一張溫暖夢幻的插畫風格圖片：
            「{message}」
            風格：柔和水彩，溫暖色調，夢幻感，適合台灣長者欣賞
            """
        else:  # nostalgic
            prompt = f"""
            根據以下懷舊描述，生成一張充滿台灣早期年代氛圍的圖片：
            「{message}」
            風格：1960-1980年代台灣風情，溫暖懷舊，柔和色調
            """

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            )
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                image_data = base64.b64encode(part.inline_data.data).decode("utf-8")
                mime_type = part.inline_data.mime_type
                return f"data:{mime_type};base64,{image_data}"

        return None

    except Exception as e:
        print(f"圖片生成失敗：{e}")
        return None