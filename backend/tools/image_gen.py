import os
import base64
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
client = None


def _get_client():
    global client
    if os.getenv("CARE4U_DEMO_MODE", "true").lower() == "true":
        return None
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        return None
    if client is None:
        client = genai.Client(api_key=api_key)
    return client

def detect_image_trigger(message: str) -> str | None:
    """
    用 LLM 判斷是否需要生成圖片
    回傳：'scene' | None
    """
    llm = _get_client()
    if llm is None:
        return None

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
            response = llm.models.generate_content(
                model="gemini-flash-lite-latest",
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
    llm = _get_client()
    if llm is None:
        return message[:50]

    prompt = f"""從以下長者說的話中，萃取出核心的視覺場景描述，用來生成插畫。

長者說：「{message}」

要求：
- 描述具體的地點、天氣、物件、氛圍（例如：台灣海邊、藍天、舊式重機、海浪、懷舊午後）
- 去除人物描述（不要提到任何人的名字或樣貌）
- 用完整的場景描述句子回答，15～40 字之間
- 只回傳場景描述，不要其他說明或標點符號結尾

範例輸出：台灣 1970 年代海邊，舊式重機停在沙灘旁，蔚藍海浪拍岸，陽光灑落，懷舊溫暖氛圍"""

    try:
        response = llm.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=200,
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
        llm = _get_client()
        if llm is None:
            return None

        # 先萃取核心場景，過濾口語雜訊
        scene = extract_scene(message)
        print(f"萃取場景：{scene}")

        prompt = f"""Create a warm nostalgic watercolor illustration of this scene: {scene}

Style: Taiwan retro landscape, soft warm colors, watercolor painting, peaceful and serene atmosphere, vintage 1970s feel.
No human faces. No modern vehicles or electronics. No text or numbers."""

        response = None
        for attempt in range(2):
            try:
                response = llm.models.generate_content(
                    model="gemini-2.5-flash-image",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"]
                    )
                )
                break
            except Exception as e:
                if "503" in str(e) and attempt == 0:
                    print(f"圖片生成 503，3s 後重試一次")
                    time.sleep(3)
                    continue
                raise

        if response is None or not response.candidates:
            print("圖片生成：無 candidates")
            return None

        cand = response.candidates[0]
        print(f"圖片回應 finish_reason={cand.finish_reason}")
        if not cand.content:
            print(f"圖片生成：content 為空（可能被安全過濾），finish_reason={cand.finish_reason}")
            return None

        for i, part in enumerate(cand.content.parts):
            if part.inline_data is not None:
                image_data = base64.b64encode(part.inline_data.data).decode("utf-8")
                mime_type = part.inline_data.mime_type
                print(f"圖片生成成功！mime_type={mime_type} size={len(part.inline_data.data)}")
                return f"data:{mime_type};base64,{image_data}"

        print("圖片生成：沒有找到圖片資料")
        return None

    except Exception as e:
        import traceback
        print(f"圖片生成失敗：{e}")
        print(traceback.format_exc())
        return None
