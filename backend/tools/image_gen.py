import os
import base64
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def detect_image_trigger(message: str) -> str | None:
    """
    用 LLM 判斷是否需要生成圖片
    回傳：'scene' | None
    """
    prompt = f"""判斷以下長者說的話，是否描述了具體的視覺場景值得生成圖片。

長者說：「{message}」

判斷標準：
- scene：只要提到任何具體的視覺元素即可觸發，例如：
  - 具體地點（老家、阿里山、稻田、廟口）
  - 具體物件（縫紉機、三合院、鐵道、榕樹）
  - 具體場景（夕陽、稻浪、廟會）
  - 夢境或懷舊中有具體畫面
- none：太模糊、只是情緒表達、沒有任何具體視覺元素

只回傳以下其中一個字：scene、none
不要有其他文字"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=10,
                )
            )
            result = response.text.strip().lower()
            print(f"圖片觸發判斷：{message[:20]} → {result}")
            if result == "scene":
                return result
            return None
        except Exception as e:
            if "503" in str(e) and attempt < 2:
                time.sleep(2)
                continue
            print(f"圖片觸發判斷失敗：{e}")
            return None
    return None


def extract_scene(message: str) -> str:
    """
    從長者原話萃取核心視覺場景描述，過濾口語雜訊
    """
    prompt = f"""從以下長者說的話中，萃取出核心的視覺場景描述。

長者說：「{message}」

要求：
- 只保留有視覺意義的場景、地點、物件、氛圍
- 去除口語贅詞（欸、啊、就是那個、跟你說喔）
- 去除人物描述（不要提到任何人的名字或樣貌）
- 用簡短的場景描述回答，不超過 30 字
- 只回傳場景描述，不要其他說明"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=50,
            )
        )
        return response.text.strip()
    except Exception as e:
        print(f"場景萃取失敗：{e}")
        return message[:50]


def generate_image(message: str, trigger_type: str) -> str | None:
    """
    根據長者說的話生成圖片
    回傳 base64 編碼的圖片字串，失敗回傳 None
    """
    try:
        # 先萃取核心場景，過濾口語雜訊
        scene = extract_scene(message)
        print(f"萃取場景：{scene}")

        prompt = f"""生成一張適合台灣長者欣賞的溫暖懷舊風景插畫。

場景描述：{scene}

風格要求：
- 台灣早期農村或城市風情，溫暖柔和色調
- 水彩或油畫插畫風格，帶有懷舊感
- 光線溫暖，氛圍寧靜祥和

嚴格禁止：
- 禁止出現任何人類面孔或具體人像（可以有模糊背影但不可有臉）
- 禁止出現現代汽車、電子產品、手機、電腦
- 禁止出現現代建築、柏油路、現代電線桿
- 禁止出現任何文字或數字"""

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            )
        )

        print(f"圖片回應 parts 數量：{len(response.candidates[0].content.parts)}")
        for i, part in enumerate(response.candidates[0].content.parts):
            print(f"Part {i}: has_inline_data={part.inline_data is not None}")
            if part.inline_data is not None:
                image_data = base64.b64encode(part.inline_data.data).decode("utf-8")
                mime_type = part.inline_data.mime_type
                print(f"圖片生成成功！mime_type={mime_type}")
                return f"data:{mime_type};base64,{image_data}"

        print("圖片生成：沒有找到圖片資料")
        return None

    except Exception as e:
        import traceback
        print(f"圖片生成失敗：{e}")
        print(traceback.format_exc())
        return None