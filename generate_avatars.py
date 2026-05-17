# -*- coding: utf-8 -*-
import os
import base64
import json
from google import genai
from google.genai import types
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

avatars = [
    {
        "filename": "ai_assistant.png",
        "prompt": "Portrait of a warm friendly Taiwanese female caregiver in her 30s, upper body only, wearing a pastel pink or light blue scrubs uniform, warm genuine smile, soft natural lighting, approachable and caring expression, short neat hair, realistic illustration style, clean light background, head and shoulders composition, like a real long-term care facility staff in Taiwan"
    }
]

output_dir = Path("frontend/static/avatars")
output_dir.mkdir(parents=True, exist_ok=True)

for avatar in avatars:
    print(f"生成：{avatar['filename']}...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=avatar["prompt"],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            )
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                img_data = part.inline_data.data
                if isinstance(img_data, str):
                    img_bytes = base64.b64decode(img_data)
                else:
                    img_bytes = img_data
                output_path = output_dir / avatar["filename"]
                with open(output_path, "wb") as f:
                    f.write(img_bytes)
                print(f"✅ 儲存：{output_path}")
                break
    except Exception as e:
        print(f"❌ 失敗：{avatar['filename']}：{e}")

print("完成！")