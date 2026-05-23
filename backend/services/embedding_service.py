import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


class EmbeddingService:

    def __init__(self):
        self.model = "models/gemini-embedding-2"
        self.dimensions = 768

    def embed(self, text: str) -> list | None:
        try:
            result = _client.models.embed_content(model=self.model, contents=text)
            return result.embeddings[0].values
        except Exception as e:
            print(f"Embedding 失敗：{e}")
            return None

    def embed_batch(self, texts: list) -> list:
        return [self.embed(text) for text in texts]
