"""
將 JSON profile 的 recent_events 同步進 PostgreSQL 並產生 3072-dim embedding。
用法：cd Care4U_codex && python -m scripts.reembed_all
"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from datetime import datetime
from backend.memory.vector_store import VectorMemoryStore
from backend.memory.json_store import JsonMemoryStore
from backend.services.embedding_service import EmbeddingService

ELDER_IDS = ["W001", "C001", "L001", "Z001"]

def _upsert_event(conn, elder_id: str, event: dict) -> int | None:
    """Insert event if not already in DB (match by elder_id + content). Return row id."""
    content = event.get("event", "").strip()
    if not content:
        return None
    with conn.cursor() as cur:
        # Check if already exists
        cur.execute(
            "SELECT id FROM elder_memories WHERE elder_id=%s AND content=%s LIMIT 1",
            (elder_id, content),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        # Insert new row
        cur.execute(
            """
            INSERT INTO elder_memories
                (elder_id, content, sentiment, importance, memory_type,
                 topic_tags, spoken_at, date, persona_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                elder_id,
                content,
                event.get("sentiment", "neutral"),
                float(event.get("importance", 0.3)),
                event.get("memory_type", "short"),
                event.get("topic_tags") or [],
                event.get("spoken_at"),
                event.get("date") or datetime.now().strftime("%Y-%m-%d"),
                event.get("persona_id", "ai"),
            ),
        )
        return cur.fetchone()[0]


def run():
    memory     = VectorMemoryStore()
    json_store = JsonMemoryStore()
    embedding  = EmbeddingService()

    print(f"\n{'='*60}")
    print("JSON → PostgreSQL 同步 + 3072-dim embedding")
    print(f"{'='*60}\n")

    total_inserted = total_embedded = total_skip = total_fail = 0

    for elder_id in ELDER_IDS:
        profile = json_store.get_profile(elder_id)
        events  = profile.get("recent_events", [])
        name    = profile.get("name", elder_id)
        print(f"\n── {name}（{elder_id}）  JSON 記憶 {len(events)} 筆 ──")

        with memory._get_conn() as conn:
            if conn is None:
                print("  ✗ DB 未連線，略過")
                continue

            for event in events:
                content = event.get("event", "").strip()
                if not content:
                    continue

                mem_id = _upsert_event(conn, elder_id, event)
                if mem_id is None:
                    continue

                # Check if embedding already exists
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT embedding IS NOT NULL FROM elder_memories WHERE id=%s",
                        (mem_id,),
                    )
                    already = cur.fetchone()
                    if already and already[0]:
                        total_skip += 1
                        continue

                emb = embedding.embed(content)
                if emb is None:
                    print(f"  ✗ embed 失敗: {content[:40]}")
                    total_fail += 1
                    continue

                ok = memory.save_event_embedding(mem_id, emb)
                if ok:
                    print(f"  ✓ [{mem_id}] {content[:50]}")
                    total_embedded += 1
                else:
                    print(f"  ✗ 儲存失敗 [{mem_id}]: {content[:40]}")
                    total_fail += 1

                time.sleep(0.15)   # rate limit buffer

        # Print summary for this elder
        with memory._get_conn() as conn:
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*), COUNT(embedding) FROM elder_memories WHERE elder_id=%s",
                        (elder_id,),
                    )
                    total_r, emb_r = cur.fetchone()
                    print(f"  → DB: {total_r} 筆，其中 {emb_r} 筆有 embedding")

    print(f"\n{'='*60}")
    print(f"新 embed：{total_embedded} 筆  跳過（已有）：{total_skip} 筆  失敗：{total_fail} 筆")
    print(f"{'='*60}")
    print("✅ 完成")

if __name__ == "__main__":
    run()
