"""
臨時腳本：用真實系統跑一次對話，顯示 RAG 召回內容和 AI 回應。
用法：python rag_demo_run.py
"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from backend.memory.vector_store import VectorMemoryStore
from backend.services.embedding_service import EmbeddingService
from backend.services.llm_service import LLMService

ELDER_ID  = "W001"
MESSAGE   = "最近常常想起以前和太太的事。"
PERSONA_ID = None   # None = active_persona

print("=" * 60)
print(f"長者：{ELDER_ID}")
print(f"訊息：{MESSAGE}")
print("=" * 60)

# ── 初始化 ─────────────────────────────────────────────────────
memory    = VectorMemoryStore()
embedding = EmbeddingService()
profile   = memory.get_profile(ELDER_ID)
active_id = PERSONA_ID or profile.get("active_persona", "ai")

print(f"使用 persona：{active_id}")

# ── RAG 語意搜尋 ───────────────────────────────────────────────
print("\n[RAG 召回記憶]")
query_vec = embedding.embed(MESSAGE)
similar_memories = memory.search_similar_memories(
    ELDER_ID, query_vec or [], limit=5,
    persona_id=active_id, query_text=MESSAGE
)

if not similar_memories:
    print("  （無召回結果）")
else:
    for i, m in enumerate(similar_memories, 1):
        score  = m.get("similarity", m.get("score", "?"))
        source = m.get("source_type", m.get("memory_type", ""))
        text  = m.get("event", m.get("content", m.get("text", "")))
        dist  = m.get("distance", "?")
        dist_str = f"{float(dist):.4f}" if dist != "?" else "?"
        tags  = m.get("topic_tags", [])
        print(f"  [{i}] distance={dist_str}  [{source}]  tags={tags}")
        print(f"       {text[:120]}")

# ── 重要記憶（高重要度） ────────────────────────────────────────
_SAFETY_TAGS = {"安全警報", "趨勢警報"}
important_memories = [
    m for m in memory.get_important_memories(
        ELDER_ID, importance_threshold=0.7, limit=12, persona_id=active_id
    )
    if not _SAFETY_TAGS.intersection(m.get("topic_tags") or [])
][:8]

print(f"\n[重要記憶注入] {len(important_memories)} 筆(importance >= 0.7)")
for m in important_memories:
    text = m.get("event", m.get("content", m.get("text", "")))
    print(f"  - {text[:80]}")

# ── LLM 生成回應 ───────────────────────────────────────────────
personas = profile.get("personas", {})
active_persona = personas.get(active_id, {})

llm = LLMService(os.getenv("MAGIC_MODEL", "gemini-2.5-flash"))
conv_history = memory.load_conversation(ELDER_ID, active_id)

print(f"\n[AI 生成回應]（model={os.getenv('MAGIC_MODEL','gemini-2.5-flash')}）")
response = llm.chat(
    profile=profile,
    conversation_history=conv_history[-4:],
    user_message=MESSAGE,
    recent_messages=conv_history[-4:],
    important_memories=important_memories,
    similar_memories=similar_memories,
    active_persona=active_persona,
)

print()
print(f"AI（{active_id}）：{response}")
print("=" * 60)
print("\n[海報用摘要]")
print(f"長者：{MESSAGE}")
print()
print("[RAG 召回片段]")
for i, m in enumerate(similar_memories[:3], 1):
    text = m.get("event", m.get("content", m.get("text", "")))
    print(f"  「{text[:60]}」")
print()
print(f"AI 回應：{response}")
