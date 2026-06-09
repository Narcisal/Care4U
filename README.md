# Care4U — Personality-Driven AI Companion System for Older Adults

> **NCKU Computer Science Capstone Project**
> Developing a Personality-Driven AI Companion System for Older Adults Using RAG
> *顏孜芸 F74124040 · Advisor: Prof. 陳鸞亮*

---

## Overview

Care4U is an AI companion system built for Taiwanese long-term care scenarios. It enables older adults to have warm, personalized conversations with AI companions modeled after their family members, while giving caregivers a professional dashboard for safety monitoring and profile management.

The system is designed to run entirely on a single local machine — no cloud infrastructure required beyond the Gemini API key.

**Key achievements:**
- RAG memory recall rate: **97.1%**
- iSafe safety detection accuracy: **98%** (49/50)
- End-to-end response latency: **4.4s** (AI) + **1.4s** (TTS edge-tts)
- End-to-end perceived latency with streaming TTS: **5.8–6.9s**

---

## Features

### Elder-Facing Companion Interface

- **Family persona selection** — Elder chooses a companion (daughter, son, grandchild, etc.) before chatting
- **Persona-aware conversation** — The AI responds as the selected family member with consistent tone, shared memories, and personalized context
- **Voice input / output** — Speech-to-text (Whisper / BreezeVoice) and text-to-speech (XTTS voice cloning → edge-tts → Windows SAPI fallback)
- **Streaming TTS** — First sentence plays while the rest is still generating; reduces perceived latency by ~2s
- **AI nostalgic illustration** — When the elder mentions a vivid scene (e.g., "I used to ride motorcycles to the beach"), the system generates a warm watercolor illustration in the background and displays it beside the persona avatar
- **Breathing ambient UI** — Gentle pulsing ring animation around the persona portrait; persists while image is shown

### RAG Memory System

- **Long-term conversation memory** — Every conversation turn is embedded (3072-dim via Gemini) and stored in PostgreSQL + pgvector
- **Semantic retrieval** — Top-5 most relevant memories are retrieved per query using cosine similarity
- **Deduplication** — `DISTINCT ON (content)` prevents the same memory from occupying multiple retrieval slots
- **Short-term + long-term injection** — Recent turns + high-importance events both injected into each prompt
- **Biography and family notes** — Structured profile fields, hobbies, health notes, and caregiver-written family observations enrich the context
- **JSON fallback** — If PostgreSQL is unavailable, keyword-based retrieval from local JSON files keeps the system functional

### iSafe Safety Monitoring

Three-tier safety classification runs in parallel with conversation generation:

| Level | Trigger | Action |
|---|---|---|
| **Level 0** — Normal | Regular conversation | Standard reply |
| **Level 1** — Low mood | Emotional distress detected by LLM | Reply + auto-log event |
| **Level 2** — Physical concern | Body-related distress detected by LLM | Reply + notify caregiver |
| **Level 3** — Emergency | Keywords: 跌倒 / 心臟 / 昏倒 (fall, heart, faint) | Bypass LLM → instant emergency message + alert |

- Level 3 is triggered by a fast keyword check (zero LLM cost, sub-millisecond)
- iSafe runs concurrently with MagicAI — does not add to perceived latency
- Safety events are stored in the profile and visible in the caregiver dashboard with acknowledgement mechanism

### Caregiver Admin Dashboard

- **Profile management** — Edit basic info, hobbies, health notes, diet, sensitivity notes
- **Persona management** — Create / edit family companion personas with photo and voice upload
- **Biography drafting** — Generate biography from profile fields and optional Tavily web search
- **Conversation history** — Review full conversation history per elder and persona
- **Safety event review** — View iSafe events with severity, acknowledge and track resolution
- **Memory status** — View recent events, important memories, and RAG retrieval checks
- **Agent activity logs** — Filtered per elder, shows each component's timing and decision path
- **Role-based access** — `viewer` / `caregiver` / `admin` roles with optional Basic Auth

---

## System Architecture

```
Elder Voice / Text Input
        │
        ▼
  FastAPI Backend
        │
        ├─── Decision Agent (orchestrator)
        │         ├── quick_keyword_check()  ──→ Level 3 emergency bypass
        │         ├── MagicAI Agent          ──→ persona-aware response (streaming)
        │         ├── iSafe Agent            ──→ emotion + safety classification (parallel)
        │         ├── Memory Store           ──→ RAG retrieval + write-back
        │         ├── Image Gen Tool         ──→ nostalgic watercolor (background async)
        │         └── Health Search Tool     ──→ health-topic background info (background async)
        │
        ├─── TTS Service
        │         └── XTTS → edge-tts → Windows SAPI (priority fallback chain)
        │
        └─── STT Service
                  └── Whisper / BreezeVoice ASR

Caregiver Admin UI
        │
        └─── Profile / Persona / Safety / Memory / Logs API
```

### Agent Components

**MagicAI** — The conversation agent. Builds responses using the elder profile, active companion persona, family notes, biography, recent memories, and RAG-retrieved similar memories. Streams output token-by-token.

**iSafe** — The safety classifier. Runs in a parallel thread; uses a fast keyword check for Level 3 emergencies and an LLM classification for Levels 0–2. Produces `escalation_level`, `emotion`, `sentiment`, and optional `trend_alert`.

**Decision** — The orchestration layer. Manages `asyncio` background tasks for image generation and health search, coordinates TTS selection, handles streaming SSE output, and writes memory events after each turn.

---

## Demo Elders

| Elder ID | Name | Persona Focus |
|---|---|---|
| `W001` | 王大明 Wang Daming | Retired engineer, Teresa Teng fan, chess; safety-alert demo |
| `C001` | 陳秀英 Chen Xiuying | Retired teacher, gardening, cooking, family warmth |
| `L001` | 林月琴 Lin Yueqin | Former tailor, mild dementia care scenario |
| `Z001` | (Extended demo) | Rich biographical events; multi-persona RAG benchmark |

---

## Project Structure

```
Care4U_codex/
├── backend/
│   ├── main.py                  FastAPI app, routes, SSE streaming, background task pool
│   ├── agents/
│   │   ├── decision.py          Orchestrates all agents; streaming + async image/health tasks
│   │   ├── magic_ai.py          Persona-aware LLM conversation with RAG injection
│   │   └── i_safe.py            Three-tier safety classification; trend monitoring
│   ├── services/
│   │   ├── llm_service.py       Gemini 2.5 Flash integration; chat, streaming, embedding
│   │   ├── stt_service.py       Whisper + BreezeVoice ASR; pooled workers
│   │   ├── tts_service.py       XTTS voice cloning → edge-tts → Windows SAPI fallback
│   │   └── embedding_service.py Gemini text-embedding-004 (3072-dim)
│   ├── memory/
│   │   ├── json_store.py        JSON-based profile, event, and conversation storage
│   │   └── vector_store.py      PostgreSQL + pgvector with DISTINCT ON deduplication
│   ├── tools/
│   │   ├── image_gen.py         AI nostalgic watercolor generation (gemini-2.5-flash-image)
│   │   ├── health_search.py     Health-topic background search
│   │   └── search_service.py    Tavily biography research
│   └── data/
│       ├── elders/              JSON profiles for W001, C001, L001, Z001
│       └── schema.sql           PostgreSQL schema with pgvector
├── frontend/
│   ├── index.html               Elder companion UI (persona panel, image overlay layout)
│   ├── admin.html               Caregiver admin dashboard
│   ├── app.js                   SSE streaming, background task polling, TTS queue, UI logic
│   └── avatars/                 Demo persona photo assets
├── scripts/
│   ├── streaming_tts_bench.py   End-to-end latency benchmark (streaming vs. full-text TTS)
│   └── reembed_all.py           Re-embed all memories after dimension change
├── tests/                       iSafe and RAG evaluation test sets
├── requirements.txt
├── .env.example
└── rag_demo_run.py              Quick RAG retrieval + LLM demo script
```

---

## Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/Narcisal/Care4U.git
cd Care4U_codex
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with at minimum:

```env
GEMINI_API_KEY=your_gemini_api_key_here
CARE4U_DEMO_MODE=true
DB_ENABLED=false
```

For full RAG functionality, also enable PostgreSQL:

```env
DB_ENABLED=true
DB_HOST=localhost
DB_PORT=5432
DB_NAME=aicaeru
DB_USER=postgres
DB_PASSWORD=your_password
```

### 3. (Optional) Initialize PostgreSQL

```bash
psql -d aicaeru -f backend/data/schema.sql
```

Then seed embeddings for existing elder profiles:

```bash
python scripts/reembed_all.py
```

### 4. Start the Server

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Open the App

| Interface | URL |
|---|---|
| Elder companion UI | http://127.0.0.1:8000/ |
| Caregiver admin dashboard | http://127.0.0.1:8000/admin |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Required for chat, embeddings, image generation |
| `TAVILY_API_KEY` | — | Optional; enables biography web research |
| `CARE4U_DEMO_MODE` | `true` | Enables fallback behavior when services are unavailable |
| `MAGIC_MODEL` | `gemini-2.5-pro` | Model for MagicAI conversation |
| `ISAFE_MODEL` | `gemini-2.0-flash` | Lightweight model for iSafe classification |
| `ALLOWED_ELDER_IDS` | `W001,C001,L001` | Comma-separated list of elder IDs allowed to log in |
| `DB_ENABLED` | `false` | Enable PostgreSQL + pgvector |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5433` | PostgreSQL port |
| `DB_NAME` | `aicaeru` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | — | Database password |
| `DB_POOL_MAX` | `5` | Max PostgreSQL connections in the shared pool |
| `XTTS_URL` | `http://localhost:8082` | XTTS voice cloning API endpoint |
| `BREEZYVOICE_URL` | `http://localhost:8080` | BreezeVoice ASR endpoint |
| `STT_POOL_SIZE` | `1` | Number of concurrent STT workers |
| `STT_MODEL_SIZE` | `medium` | Whisper model size |
| `STT_DEVICE` | `cuda` | `cuda` or `cpu` |
| `AGENT_EXECUTOR_WORKERS` | `4` | Thread pool workers for parallel agent execution |
| `ADMIN_USERNAME` | `admin` | Admin dashboard username |
| `ADMIN_PASSWORD` | — | Enables Basic Auth when set |
| `ADMIN_USERS` | — | JSON map for multiple admin users and roles |

**Admin roles:**
- `viewer` — read-only access to profiles and personas
- `caregiver` — read + update care data
- `admin` — full access including session management

---

## TTS Priority Chain

For each AI response, TTS is attempted in this order:

1. **XTTS** — Voice cloning using the uploaded `.wav` sample for the active persona (most natural)
2. **edge-tts** — Microsoft cloud TTS; no setup required
3. **Windows SAPI** — Offline fallback; always available on Windows; ensures TTS never fails during a demo

Voice samples are uploaded through the caregiver admin dashboard as `.wav` files (16kHz, mono recommended).

---

## AI Image Generation

When the elder mentions a visually rich memory (detected by an LLM trigger classifier), the system:

1. **Detects** whether the message contains a visual scene (`detect_image_trigger`)
2. **Extracts** the core scene description, removing named people (`extract_scene`)
3. **Generates** a warm watercolor illustration via `gemini-2.5-flash-image`
4. **Stores** the base64 PNG in a background task result
5. **Frontend polls** `/api/elder/chat/background/{task_id}` until complete
6. **Displays** the image beside the persona avatar with a subtle overlap layout

The image generation runs asynchronously — it does not block the conversation response. The frontend continues the chat while the illustration is being generated in the background (typically 10–20 seconds).

Example trigger:
> "以前和太太騎重型機車去海邊，風吹過來真的很舒服。"
> *(We used to ride motorcycles to the beach together — the wind felt so good.)*

---

## Performance Benchmarks

| Metric | Value |
|---|---|
| RAG memory recall rate | **97.1%** |
| iSafe safety detection accuracy | **98.0%** (49/50) |
| AI response latency (Gemini) | **4.4s** avg |
| TTS latency — edge-tts | **1.4s** avg |
| TTS latency — XTTS (voice clone) | **4.9s** avg |
| Perceived end-to-end latency (streaming TTS) | **5.8–6.9s** |

*Measured on a single local machine (Windows, no GPU for inference) with Gemini API.*

Streaming TTS reduces perceived latency by starting audio playback as soon as the first sentence is generated, rather than waiting for the full response.

---

## RAG Architecture Details

Memory retrieval uses a two-layer approach:

**Semantic search (pgvector)**
```sql
SELECT event, sentiment, importance, memory_type, topic_tags, date, distance
FROM (
    SELECT DISTINCT ON (content)
           content AS event, sentiment, importance,
           memory_type, topic_tags, date,
           embedding <=> $1::vector AS distance
    FROM elder_memories
    WHERE elder_id = $2
      AND embedding IS NOT NULL
    ORDER BY content, distance ASC
) deduped
ORDER BY distance ASC
LIMIT 5;
```

`DISTINCT ON (content)` prevents duplicate conversation records from filling retrieval slots.

**Important memory injection**

High-importance events (importance ≥ 0.7) are injected separately, ensuring significant life events are always present in the prompt regardless of query relevance.

**Embedding model:** `text-embedding-004` (Google), 3072 dimensions

---

## iSafe Implementation Notes

**Level 3 fast path** — `quick_keyword_check()` scans for emergency keywords (跌倒, 心臟, 昏倒) before any LLM call. If matched, the system bypasses MagicAI entirely and returns a pre-written emergency message with `escalation_level=3`. This is the critical path for real emergencies.

**Concurrent execution** — iSafe and MagicAI run in parallel using a shared `ThreadPoolExecutor`. iSafe result is awaited only after MagicAI streaming completes, so it adds zero latency to the first response token.

**Trend detection** — iSafe tracks negative sentiment accumulation across conversations and can generate trend alerts visible to caregivers.

---

## Running Evaluations

**RAG recall test:**
```bash
python backend/tools/rag_evaluation.py
```

**iSafe accuracy test:**
```bash
python -m pytest tests/ -v
```

**Streaming TTS benchmark:**
```bash
python scripts/streaming_tts_bench.py --elder W001
```

**Quick RAG demo (prints retrieved memories + AI response):**
```bash
python rag_demo_run.py
```

---

## Demo Walkthrough

1. Start the server and open http://127.0.0.1:8000/
2. Select elder **王大明 (W001)** and choose the **兒子** persona
3. Type: `最近常常想起以前和太太的事` — observe RAG memory injection in the response
4. Type: `以前和太太騎重型機車去海邊，風吹過來真的很舒服` — wait ~15s for the watercolor illustration
5. Type: `我剛剛跌倒了` — observe instant Level 3 emergency response (no LLM delay)
6. Open http://127.0.0.1:8000/admin to review safety events in the caregiver dashboard

---

## Safety and Ethics

Care4U is a research prototype and **not** a certified medical device.

- Safety alerts must be reviewed by human caregivers — the system cannot guarantee detection of all emergencies
- Voice samples uploaded for XTTS contain biometric data and should remain stored locally
- Deceased or sensitive family personas should be used carefully, especially with cognitively impaired users
- Enable `ADMIN_PASSWORD` or `ADMIN_USERS` in non-demo deployments

---

## Future Work

- Taiwanese Mandarin dialect support (improved STT fine-tuning)
- Docker Compose deployment packaging
- Longer-term memory consolidation (weekly biography auto-update)
- Multi-elder session isolation for real care facility deployment
- Richer caregiver analytics (emotion trend charts, safety heatmaps)
- iSafe two-stage optimization (further reduce LLM trigger rate)
