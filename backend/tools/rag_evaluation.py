from backend.memory.vector_store import VectorMemoryStore


def evaluate_rag_queries(elder_id: str, queries: list[dict], limit: int = 5) -> dict:
    """Evaluate memory retrieval with lightweight hit-rate metrics.

    Query format:
    {
      "query": "豆漿很好喝",
      "expected": ["豆漿"]
    }
    """
    memory = VectorMemoryStore()
    rows = []
    hits = 0

    for item in queries:
        query = str(item.get("query", "")).strip()
        expected = [str(x) for x in item.get("expected", []) if str(x).strip()]
        retrieved = memory.search_similar_memories(
            elder_id,
            [],
            limit=limit,
            query_text=query,
        )
        retrieved_text = "\n".join(r.get("event", "") for r in retrieved)
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
        "rows": rows,
    }
