import os

from backend.memory.vector_store import VectorMemoryStore
from backend.services.embedding_service import EmbeddingService


def evaluate_rag_queries(elder_id: str, queries: list[dict], limit: int = 5) -> dict:
    """Evaluate memory retrieval with lightweight hit-rate metrics.

    Query format:
    {
      "query": "豆漿很好喝",
      "expected": ["豆漿"]
    }
    """
    memory = VectorMemoryStore()
    embedder = EmbeddingService()
    rows = []
    hits = 0
    embedding_queries = 0

    for item in queries:
        query = str(item.get("query", "")).strip()
        expected = [str(x) for x in item.get("expected", []) if str(x).strip()]
        # 永遠走 JSON token-overlap fallback：
        # 長者記憶存在 JSON 檔而非 postgres elder_memories 表，
        # 傳空 embedding 強制走 json_store.search_similar_memories。
        query_embedding = []
        retrieved = memory.search_similar_memories(
            elder_id,
            query_embedding,
            limit=limit,
            query_text=query,
        )
        retrieved_text = "\n".join(
            " ".join([
                str(r.get("event", "")),
                str(r.get("reason", "")),
                " ".join(r.get("topic_tags", []) or []),
            ])
            for r in retrieved
        )
        hit = bool(expected) and any(term in retrieved_text for term in expected)
        if hit:
            hits += 1
        rows.append({
            "query": query,
            "expected": expected,
            "hit": hit,
            "retrieved": [
                {
                    "event": r.get("event", ""),
                    "date": r.get("date", ""),
                    "importance": r.get("importance", 0),
                    "rag_score": r.get("rag_score"),
                }
                for r in retrieved
            ],
        })

    total = len(rows)
    return {
        "elder_id": elder_id,
        "total": total,
        "hits": hits,
        "hit_rate": round(hits / total, 3) if total else 0.0,
        "embedding_queries": embedding_queries,
        "rows": rows,
    }
