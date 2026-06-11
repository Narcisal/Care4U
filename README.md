# Care4U — Personality-Driven AI Companion System for Older Adults

> **NCKU Computer Science Capstone Project**
> Developing a Personality-Driven AI Companion System for Older Adults Using RAG
> *顏孜芸 F74124040 · Advisor: Prof. 陳鸞亮*

---

## Overview

Care4U is an AI companion system built for Taiwanese long-term care scenarios. It enables older adults to have warm, personalized conversations with AI companions modeled after their family members, while giving caregivers a professional dashboard for safety monitoring and profile management.

The system is designed to run entirely on a single local machine — no cloud infrastructure required beyond the Gemini API key (optional OpenAI key enables automatic fallback).

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
- **Voice input / output** — Speech-to-text (Whisper / BreezeVoice) and text-to-speech (XTTS voice cloning → LuxTTS → edge-tts → Windows SAPI fallback)
- **Streaming TTS** — First sentence plays while the rest is still generating; reduces perceived latency by ~2s
- **AI nostalgic illustration** — When the elder mentions a vivid scene (e.g., "I used to ride motorcycles to the beach"), the system generates a warm watercolor illustration in the background and displays it beside the persona avatar
- **Breathing ambient UI** — Gentle pulsing ring animation around the persona portrait; persists while image is shown

### RAG Memory System

- **Long-term conversation memory** — Every conversation turn is embedded (3072-dim via Gemini) and stored in PostgreSQL + pgvector
- **Semantic retrieval** — Top-5 most relevant memories are retrieved per query using cosine similarity
- **Deduplication** — `DISTINCT ON (content)` prevents the same memory from occupying multiple retrieval slots
- **Short-term + long-term injection** — Recent turns + high-importance events both injected into each prompt
- **Biography and family notes** — Structured profile fields, hobbies, health notes, and caregiver-written family observations enrich the context
- **Biography auto-update** — Every 10 conversation turns, MagicAI drafts an updated biography from important memories (importance ≥ 0.7); requires at least 2 qualifying memories; skipped if an admin manually edited the biography
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
- If LLM returns Level 1 but the message contains physical symptom phrases (腫、痠痛、腿軟、差點跌 etc.), iSafe automatically escalates to Level 2
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

## Hardware Requirements

The system is designed to run on a single Windows machine without a dedicated GPU for inference (all heavy LLM work is offloaded to the Gemini API).

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 64-bit | Windows 11 |
| RAM | 8 GB | 16 GB |
| Disk | 4 GB free | 8 GB free (Whisper model + voice samples) |
| CPU | 4-core | 8-core (for STT + parallel agents) |
| GPU | — | NVIDIA GPU (speeds up Whisper STT; set `STT_DEVICE=cuda`) |
| Internet | Required | Required (Gemini API, edge-tts) |

**Optional local services** (each run as a separate process):

| Service | Port | Purpose |
|---|---|---|
| XTTS v2 | 8082 | Voice cloning TTS |
| LuxTTS | 8081 | Local neural TTS |
| BreezeVoice | 8080 | Taiwanese Mandarin ASR |
| PostgreSQL + pgvector | 5432/5433 | Vector memory store |

All optional services degrade gracefully — the system falls back to edge-tts (Microsoft cloud) and Whisper (bundled) if they are unavailable.

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
        │         └── XTTS (circuit breaker + auto-restart) → LuxTTS → edge-tts → Windows SAPI
        │
        └─── STT Service
                  └── Whisper / BreezeVoice ASR

Caregiver Admin UI
        │
        └─── Profile / Persona / Safety / Memory / Logs API
```

### Agent Components

**MagicAI** — The conversation agent. Builds responses using the elder profile, active companion persona, family notes, biography, recent memories, and RAG-retrieved similar memories. Streams output token-by-token. Keeps up to **50 conversation turns** in memory per session (older turns are trimmed automatically). LLM fallback chain: **Gemini → OpenAI GPT-4o-mini → keyword hardcoded responses**. Fallback triggers only on retryable errors (503, rate limit, timeout); prompt-level errors do not trigger fallback.

**iSafe** — The safety classifier. Runs in a parallel thread; uses a fast keyword check for Level 3 emergencies and an LLM classification for Levels 0–2. Produces `escalation_level`, `emotion`, `sentiment`, and optional `trend_alert`. Trend alerts have a **2-hour cooldown** to prevent duplicate notifications.

**Decision** — The orchestration layer. Manages `asyncio` background tasks for image generation and health search, coordinates TTS selection, handles streaming SSE output, and writes memory events after each turn.

---

## Demo Elders

| Elder ID | Name | Persona Focus |
|---|---|---|
| `W001` | 王大明 Wang Daming | Retired engineer, Teresa Teng fan, chess; safety-alert demo |
| `C001` | 陳秀英 Chen Xiuying | Retired teacher, gardening, cooking, family warmth |
| `L001` | 林月琴 Lin Yueqin | Former tailor, mild dementia care scenario |
| `Z001` | (Extended demo) | Rich biographical events; multi-persona RAG benchmark. Add to `ALLOWED_ELDER_IDS` to enable. |

---

## Project Structure

```
Care4U_codex/
├── backend/
│   ├── main.py                  FastAPI app entry point; session pool, admin auth lockout
│   ├── elder_sessions.py        Optional legacy PIN/token compatibility helpers
│   ├── agents/
│   │   ├── decision.py          Orchestrates all agents; streaming + async image/health tasks
│   │   ├── magic_ai.py          Persona-aware LLM conversation with RAG injection (50-turn limit)
│   │   └── i_safe.py            Three-tier safety classification; trend monitoring (2h cooldown)
│   ├── routers/
│   │   ├── admin.py             Admin dashboard + session management endpoints
│   │   ├── chat.py              Elder chat + background task polling endpoints
│   │   ├── elder_session.py     Elder-facing profile/TTS APIs and optional PIN endpoints
│   │   ├── persona.py           Persona create/delete/switch/voice-upload endpoints
│   │   ├── profile.py           Profile CRUD, biography draft, safety event, family notes
│   │   └── speech.py            STT and TTS endpoints
│   ├── services/
│   │   ├── llm_service.py       Gemini → OpenAI fallback; chat, streaming, emotion analysis
│   │   ├── stt_service.py       Whisper + BreezeVoice ASR; pooled workers
│   │   ├── tts_service.py       XTTS (circuit breaker) → edge-tts → SAPI; emoji stripping
│   │   └── embedding_service.py Gemini gemini-embedding-2 (3072-dim)
│   ├── memory/
│   │   ├── json_store.py        JSON-based profile, event, and conversation storage
│   │   └── vector_store.py      PostgreSQL + pgvector with DISTINCT ON deduplication
│   ├── tools/
│   │   ├── image_gen.py         AI nostalgic watercolor generation (disabled in DEMO_MODE)
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
│   ├── streaming_tts_bench.py   End-to-end latency benchmark; --elder / --persona-id flags
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
CARE4U_DEMO_MODE=false   # set true to skip image generation (useful on low-spec machines)
DB_ENABLED=false
```

For full RAG functionality, also enable PostgreSQL:

```env
DB_ENABLED=true
DB_HOST=localhost
DB_PORT=5433
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
| `OPENAI_API_KEY` | — | Optional; enables OpenAI GPT fallback when Gemini is unavailable |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model used for fallback |
| `CARE4U_DEMO_MODE` | `false` | `true` disables AI image generation; set `false` for full demo |
| `MAGIC_MODEL` | `gemini-2.5-flash` | Model for MagicAI conversation |
| `ISAFE_MODEL` | `gemini-2.5-flash` | Lightweight model for iSafe classification |
| `LLM_TIMEOUT_MS` | `15000` | Timeout (ms) for a single Gemini API call |
| `LLM_MAX_CONCURRENT` | `4` | Max simultaneous LLM requests (shared by Gemini + OpenAI) |
| `ALLOWED_ELDER_IDS` | `W001,C001,L001,Z001` | Comma-separated list of elder IDs allowed to log in |
| `DB_ENABLED` | `false` | Enable PostgreSQL + pgvector |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5433` | PostgreSQL port |
| `DB_NAME` | `aicaeru` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | — | Database password |
| `XTTS_URL` | `http://localhost:8082` | XTTS v2 voice cloning API endpoint |
| `XTTS_RESTART_SCRIPT` | — | Absolute path to `restart_xtts.ps1`; enables auto-restart on CUDA crash |
| `BREEZYVOICE_URL` | `http://localhost:8080` | BreezeVoice ASR endpoint |
| `STT_POOL_SIZE` | `1` | Number of concurrent STT workers |
| `STT_MODEL_SIZE` | `small` | Whisper model size |
| `STT_DEVICE` | `cpu` | `cuda` or `cpu` |
| `MAX_SESSIONS` | `100` | Max concurrent elder sessions; oldest session evicted when exceeded (LRU) |
| `ADMIN_PASSWORD` | — | Enables admin auth when set |

---

## Elder Selection and Browser Session Flow

The current elder UI is optimized for a supervised local demo. It does not require
a PIN or Bearer token:

```
Open /?elder=W001
  └── app.js validates the elder through GET /api/elder/profile?elder_id=W001
      └── stores care4u_elder_id in sessionStorage for the current browser tab
          ├── elder_id is sent in chat / greet / TTS request bodies
          └── elder_id is sent as a query parameter for profile / persona reads
```

Each browser tab also creates a random `session_id` in `sessionStorage`. The
backend uses `{elder_id}:{session_id}:{persona_id}` to isolate in-memory
conversation state. In localhost demo mode, the elder selector can replace the
stored elder ID and reload the page.

This is an identity-selection mechanism, not strong authentication. Deployments
that expose the elder UI beyond a trusted device or local network should add an
authenticated gateway or restore token enforcement.

The backend still contains the older PIN/token endpoints
(`/api/admin/elder-pin`, `/api/elder-login`, and revoke helpers) for compatibility
and experiments, but the current frontend does not call them.

**Elder ID auto-generation:** When an admin creates a new elder, the system derives the ID from the first character of the family name using a built-in surname table (王→W, 陳→C, 林→L, 張→Z, 黃→H, 楊→Y …) and appends a 3-digit sequence number (e.g., `W001`, `W002`).

---

## Admin Onboarding (New Elder Flow)

```
1. Preview elder ID (optional)
   GET /api/admin/elders/preview-id?name=王大明
   → { "elder_id": "W002" }

2. Create elder
   POST /api/admin/elders
   Body: { "name": "王大明", "gender": "male", "former_job": "engineer", ... }
   → Profile JSON written to backend/data/elders/W002.json
   → Default "ai" persona created automatically
   → elder_id added to in-memory ALLOWED_ELDER_IDS

3. (Optional) Draft biography
   POST /api/profile/biography-preview-new
   Body: { "name": "...", "birth_year": ..., "hometown": "...", ... }
   → Uses Tavily web search for cultural context (does not require the elder to exist yet)

4. Upload persona photo
   POST /api/profile/persona/upload-avatar

5. Upload voice sample for XTTS (optional)
   POST /api/profile/persona/upload-voice
   Recommended: mono WAV, 16 kHz, ≥ 6 seconds of clear speech

6. Open the elder UI
   `http://localhost:8000/?elder=W002`
   → The selected elder ID is stored in that browser tab's sessionStorage

   Optional legacy compatibility: the backend PIN/token endpoints remain
   available, but they are not required or used by the current frontend.
```

---

## TTS Priority Chain

For each AI response, TTS is attempted in this order:

| Priority | Engine | Port | Notes |
|---|---|---|---|
| 1 | **XTTS v2** | 8082 | Voice cloning using the uploaded `.wav` sample; most natural |
| 2 | **edge-tts** | — | Microsoft cloud TTS; emotion-aware prosody (rate/pitch/volume adjusted per detected emotion) |
| 3 | **Windows SAPI** | — | Offline fallback; always available on Windows |

The system tries each engine in sequence and moves to the next if the current one is unreachable or returns an error. This ensures TTS never fails silently during a demo.

Voice samples are uploaded through the caregiver admin dashboard as `.wav` files (16 kHz, mono recommended). XTTS requires a voice sample; the other engines work without one.

**XTTS circuit breaker and auto-restart:**
- Text is split into chunks of max **40 characters** before sending to XTTS (Chinese tokenizer limitation)
- Emoji and special characters are stripped at three layers: LLM prompt prohibition → backend `_strip_emoji()` → frontend `stripEmoji()`
- After **2 consecutive failures**, XTTS is bypassed for a cooldown period and edge-tts handles all requests
- On CUDA crash (device-side assert), the XTTS process calls `os._exit(1)` and the `run_loop.py` wrapper auto-restarts it
- A background health probe detects when XTTS is back online and clears the cooldown immediately
- Set `XTTS_RESTART_SCRIPT` in `.env` to enable the Care4U-side restart trigger

**edge-tts emotion prosody mapping:**

| Emotion | Rate | Pitch | Volume |
|---|---|---|---|
| `happy` | +20% | +10 Hz | +5% |
| `comfort` | −20% | −5 Hz | −5% |
| `urgent` | +15% | +8 Hz | +15% |
| `remind` | −8% | +2 Hz | +0% |
| `normal` | +0% | +0 Hz | +0% |

---

## Session Management

**Concurrent session limit:** `MAX_SESSIONS=100` (default). When the server receives a new chat request and the active session count exceeds this limit, the session with the oldest `last_seen` timestamp is evicted (LRU). Each session is keyed by `{elder_id}:{session_id}:{persona_id}`.

**Idle timeout:** Sessions idle for more than 1 hour are automatically cleaned up before LRU eviction is considered.

**Conversation history limit:** MagicAI keeps the most recent **50 turns** per session in memory. Older turns are trimmed automatically; they remain stored in the JSON/DB history and can be retrieved from the admin dashboard.

**Biography auto-update:** Every 10 conversation turns, the Decision agent schedules a background biography update. The update fetches recent events with importance ≥ 0.7, constructs an updated draft via LLM, validates it (length check, key-fact preservation), and writes it to the profile. If an admin has manually edited the biography, the auto-update is skipped to preserve the human edit.

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

> **Note:** Image generation is disabled when `CARE4U_DEMO_MODE=true` (the default). To enable it, set `CARE4U_DEMO_MODE=false` and ensure `GEMINI_API_KEY` is configured.

Example trigger:
> "以前和太太騎重型機車去海邊，風吹過來真的很舒服。"
> *(We used to ride motorcycles to the beach together — the wind felt so good.)*

---

## iSafe Implementation Notes

**Level 3 fast path** — `quick_keyword_check()` scans for emergency keywords (跌倒, 心臟, 昏倒) before any LLM call. If matched, the system bypasses MagicAI entirely and returns a pre-written emergency message with `escalation_level=3`. This is the critical path for real emergencies.

**Physical symptom auto-escalation (L1 → L2)** — When the LLM returns Level 1, iSafe applies a second-pass check for physical symptom phrases: 腫、痠痛、使不上力、腿軟、膝軟、記性、忘了藥、胃口差、吃不下、差點跌、差點倒. Any match automatically bumps the result to Level 2. This conservative bias reduces the risk of under-reporting physical decline.

**Concurrent execution** — iSafe and MagicAI run in parallel using a shared `ThreadPoolExecutor`. iSafe result is awaited only after MagicAI streaming completes, so it adds zero latency to the first response token.

**Trend detection and cooldown** — iSafe tracks the last 5 detected emotions per session. Two trend conditions trigger a caregiver alert:
- Three consecutive `urgent` emotions → "連續三次偵測到緊急狀況"
- Three consecutive `comfort`/`urgent` emotions → "長者持續情緒低落"

A **2-hour cooldown** prevents the same trend alert from firing repeatedly: iSafe scans the last 30 recent events for a prior "趨勢警報" tag and suppresses the new alert if one was recorded within the past 2 hours.

---

## API Reference

All endpoints are served at `http://localhost:8000`.

### Optional Legacy PIN APIs

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/elder-login` | Legacy: submit PIN and receive a Bearer token |
| `GET` | `/api/system/mode` | Returns current demo/auth mode |

### Elder-Facing APIs (elder_id scoped)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/elder/profile?elder_id=...` | Fetch the selected elder's profile |
| `GET` | `/api/elder/personas?elder_id=...` | List the selected elder's personas |
| `POST` | `/api/elder/tts` | TTS synthesis; `elder_id` is supplied in the body |
| `GET` | `/api/elder/chat/background/{task_id}?elder_id=...` | Poll the selected elder's background task |

### Chat

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Elder companion UI |
| `POST` | `/api/switch-elder` | Switch active elder + persona |
| `POST` | `/api/greet` | Generate greeting for selected persona |
| `POST` | `/api/chat` | Send message; `?stream=true` for SSE streaming |
| `GET` | `/api/chat/background/{task_id}` | Poll background task (image, health) |

### Speech

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/stt` | Transcribe audio (Whisper / BreezeVoice) |
| `GET` | `/api/stt/status` | STT worker pool status |
| `POST` | `/api/tts` | TTS synthesis (admin / unauthenticated) |
| `POST` | `/api/stt/language` | Set STT language |

### Profile & Personas (Admin)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/profile/{elder_id}` | Get elder profile |
| `POST` | `/api/profile/save` | Update profile fields |
| `POST` | `/api/profile/save-biography` | Save biography |
| `POST` | `/api/profile/biography-draft` | Draft biography from profile + Tavily search |
| `POST` | `/api/profile/biography-preview-new` | Preview biography for a not-yet-created elder |
| `POST` | `/api/profile/family-note/add` | Add caregiver family note |
| `POST` | `/api/profile/family-note/delete` | Remove family note |
| `GET` | `/api/history/{elder_id}` | Full conversation history |
| `GET` | `/api/safety/{elder_id}` | iSafe event list |
| `PATCH` | `/api/isafe/{elder_id}/events/{index}/acknowledge` | Acknowledge a safety event |
| `GET` | `/api/agent-logs` | Agent timing and decision logs |
| `GET` | `/api/profile/{elder_id}/personas` | List personas |
| `POST` | `/api/profile/persona/add` | Add persona |
| `POST` | `/api/profile/persona/delete` | Delete persona |
| `POST` | `/api/profile/persona/switch` | Switch active persona |
| `POST` | `/api/profile/persona/upload-voice` | Upload `.wav` voice sample for XTTS |
| `POST` | `/api/profile/persona/upload-avatar` | Upload persona photo |

### Admin

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin` | Caregiver admin dashboard |
| `GET` | `/api/admin/me` | Current admin user info |
| `GET` | `/api/admin/dashboard` | Dashboard summary stats |
| `GET` | `/api/admin/elders` | List allowed elders |
| `GET` | `/api/admin/elders/preview-id` | Preview auto-generated elder ID |
| `POST` | `/api/admin/elders` | Create new elder |
| `POST` | `/api/admin/elder-pin` | Legacy: issue a PIN for an elder |
| `POST` | `/api/admin/elder-session/revoke` | Legacy: revoke elder PINs and tokens |
| `GET` | `/api/admin/sessions` | List active sessions |
| `POST` | `/api/admin/sessions/clear` | Clear all sessions |

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

**Hardware context:** All measurements were taken on a single Windows 11 machine, Intel CPU, no local GPU for inference. Gemini API calls go over a standard broadband connection.

**Reproducing benchmarks:**

```bash
# iSafe accuracy + RAG recall (deterministic mock LLM, fast)
python backend/tools/phase10_evaluate.py

# iSafe accuracy + RAG recall (real Gemini calls, slower)
PHASE10_USE_REAL_ISAFE=true python backend/tools/phase10_evaluate.py

# Streaming TTS end-to-end latency (edge-tts)
python scripts/streaming_tts_bench.py --elder W001

# Streaming TTS with XTTS voice cloning
python scripts/streaming_tts_bench.py --elder W001 --persona-id son

# Full TTS engine comparison
python scripts/tts_benchmark.py --engine all --voice-path /path/to/voice.wav
```

Results are written to `reports/` as CSV + Markdown summary.

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

**Embedding model:** `gemini-embedding-2` (Google), 3072 dimensions

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

**Streaming TTS benchmark (edge-tts, default persona):**
```bash
python scripts/streaming_tts_bench.py --elder W001
```

**Streaming TTS benchmark (XTTS voice cloning, specific persona):**
```bash
python scripts/streaming_tts_bench.py --elder W001 --persona-id son
```

**Quick RAG demo (prints retrieved memories + AI response):**
```bash
python rag_demo_run.py
```

---

## Demo Walkthrough

1. Start the server and open http://127.0.0.1:8000/
2. Select elder **王大明 (W001)** and choose the **兒子** persona
3. Press and hold the microphone button to speak: `最近常常想起以前和太太的事` — the AI responds with RAG-retrieved memories injected into its reply
4. Speak: `以前和太太騎重型機車去海邊，風吹過來真的很舒服` — a nostalgic watercolor illustration appears beside the persona avatar after ~15s (requires `CARE4U_DEMO_MODE=false`)
5. Speak: `我剛剛跌倒了` — the system instantly returns a Level 3 emergency message without calling the LLM
6. Open http://127.0.0.1:8000/admin to review the triggered safety event in the caregiver dashboard

---

## Troubleshooting

**Image generation never appears**

`CARE4U_DEMO_MODE=true` disables image generation regardless of whether a Gemini key is configured. Set `CARE4U_DEMO_MODE=false` in `.env` and restart the server.

**TTS is silent or very slow**

XTTS and LuxTTS require a separately running local service. If neither is running, the system falls back to edge-tts (requires internet) and then Windows SAPI (offline). To check which engine was used, look for `tts_engine` in the agent logs at `/api/agent-logs`. To force a specific engine, ensure only the desired service is reachable (e.g., stop XTTS to test LuxTTS).

**PostgreSQL connection errors at startup**

If `DB_ENABLED=true` but PostgreSQL is not running, the server logs a warning and falls back to JSON storage. No data is lost — the JSON files in `backend/data/elders/` remain the source of truth. To disable PostgreSQL entirely, set `DB_ENABLED=false`.

**STT transcription fails or is very slow**

If `STT_DEVICE=cuda` but CUDA is not available, Whisper silently fails or is extremely slow. Set `STT_DEVICE=cpu` in `.env`. For faster CPU transcription, try `STT_MODEL_SIZE=small` (lower accuracy) or `STT_MODEL_SIZE=base`.

**Admin login returns 429 Too Many Requests**

Five consecutive failed login attempts from the same IP triggers a 60-second lockout. Wait 60 seconds and try again. If the correct credentials are unknown, check `ADMIN_PASSWORD` and `ADMIN_USERS` in `.env`.

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
