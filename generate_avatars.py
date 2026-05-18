"""
AI Care U 圖片生成腳本
使用 Gemini 生成兩組圖片：有背景版 + 無背景版
執行方式：python generate_avatars.py
"""

import os
import base64
import json
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

OUTPUT_DIR = Path("frontend/avatars/generated")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =====================================================
# 圖片定義
# =====================================================
IMAGES = [
{
        "id": "ai_assistant",
        "label": "AI 助理（左側引導角色）",
        "prompt_bg": """
            concept art, high resolution, kind elderly care assistant woman, 
            Taiwanese appearance, warm benevolent expression, 
            direct eye contact with viewer, kindest genuine smile, 
            comforting and reassuring posture, profound empathy in eyes, 
            soft natural cinematic lighting, shallow depth of field, 
            minimalist background matching warm cream color #F7F3EE, 
            soft focus, safe and secure atmosphere, 
            casual comfortable clothing in warm tones, photorealistic portrait
        """,
        "prompt_nobg": """
            concept art, high resolution, kind elderly care assistant woman,
            Taiwanese appearance, warm benevolent expression,
            direct eye contact with viewer, kindest genuine smile,
            comforting and reassuring posture, profound empathy in eyes,
            soft natural cinematic lighting, shallow depth of field,
            pure white background,
            soft focus, safe and secure atmosphere,
            casual comfortable clothing in warm tones, photorealistic portrait
        """,
        "negative": "scary, dark, red, sharp harsh edges, cold expression, distant unfriendly look, formal stiff nursing uniform, overly complex background, signature, watermark, noise, distorted face, asymmetrical features, uncanny valley, horror, sadness"
    },
]


def generate_image(prompt: str, negative: str, filename: str):
    """呼叫 Gemini 生成圖片並儲存"""
    print(f"  生成中：{filename}...")
    try:
        full_prompt = f"{prompt.strip()}\n\nAvoid the following: {negative}"
        response = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=full_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
            )
        )

        if response.generated_images:
            image_data = response.generated_images[0].image.image_bytes
            output_path = OUTPUT_DIR / filename
            with open(output_path, "wb") as f:
                f.write(image_data)
            print(f"  ✅ 已儲存：{output_path}")
            return True

        print(f"  ❌ 沒有回傳圖片：{filename}")
        return False

    except Exception as e:
        print(f"  ❌ 生成失敗：{e}")
        return False


def main():
    print("=" * 50)
    print("AI Care U 圖片生成器")
    print("=" * 50)
    print(f"輸出目錄：{OUTPUT_DIR.absolute()}")
    print()

    results = []

    for img in IMAGES:
        print(f"【{img['label']}】")

        # 有背景版
        success_bg = generate_image(
            prompt=img["prompt_bg"],
            negative=img["negative"],
            filename=f"{img['id']}_bg.png"
        )

        # 無背景版
        success_nobg = generate_image(
            prompt=img["prompt_nobg"],
            negative=img["negative"],
            filename=f"{img['id']}_nobg.png"
        )

        results.append({
            "id": img["id"],
            "label": img["label"],
            "bg": success_bg,
            "nobg": success_nobg
        })
        print()

    print("=" * 50)
    print("生成結果：")
    for r in results:
        bg_status = "✅" if r["bg"] else "❌"
        nobg_status = "✅" if r["nobg"] else "❌"
        print(f"  {r['label']}：有背景 {bg_status}  無背景 {nobg_status}")
    print("=" * 50)
    print(f"圖片儲存在：{OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    main()