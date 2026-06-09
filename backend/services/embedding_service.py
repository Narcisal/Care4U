import os
from google import genai
from dotenv import load_dotenv

load_dotenv(override=True)

_client = None


def _get_client():
    global _client
    if os.getenv("CARE4U_DEMO_MODE", "true").lower() == "true":
        return None
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        return None
    if _client is None:
        _client = genai.Client(api_key=api_key)
    return _client


class EmbeddingService:

    def __init__(self):
        self.model = "models/gemini-embedding-2"
        self.dimensions = 3072

    def embed(self, text: str) -> list | None:
        client = _get_client()
        if client is None:
            return None
        try:
            result = client.models.embed_content(model=self.model, contents=text)
            return result.embeddings[0].values
        except Exception as e:
            print(f"Embedding 失敗：{e}")
            return None

    def embed_batch(self, texts: list) -> list:
        return [self.embed(text) for text in texts]
