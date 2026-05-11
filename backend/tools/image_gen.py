def detect_image_trigger(message: str) -> str | None:
    """
    用 LLM 判斷是否需要生成圖片
    回傳：'dream' | 'nostalgic' | None
    """
    prompt = f"""判斷以下長者說的話，是否描述了具體的視覺場景值得生成圖片。

長者說：「{message}」

判斷標準：
- dream：描述了具體的夢境畫面（有場景、有人物、有動作）
- nostalgic：描述了具體的懷舊場景（有地點、有畫面、有細節）
- none：太模糊、只是提到夢或懷念、沒有具體畫面

只回傳以下其中一個字：dream、nostalgic、none
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
            if result in ["dream", "nostalgic"]:
                return result
            return None
        except Exception as e:
            if "503" in str(e) and attempt < 2:
                time.sleep(2)
                continue
            print(f"圖片觸發判斷失敗：{e}")
            return None
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
        else:
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