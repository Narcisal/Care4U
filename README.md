# AI Care U

AI Care U is a National Cheng Kung University Computer Science capstone project for AI-assisted elder companionship and caregiver support.

The system is designed around Taiwanese long-term care scenarios, where older adults may need familiar companionship, gentle conversation, safety monitoring, and caregiver oversight. It combines an elder-facing chat interface with a caregiver-facing admin dashboard for managing elder profiles, family companion personas, safety events, and demo operations.

## Motivation

Older adults in long-term care settings often experience loneliness, reduced family contact, and gradual cognitive decline. At the same time, caregivers must monitor many residents at once, making it difficult to notice subtle emotional changes or repeated safety signals.

AI Care U explores how an AI companion can support this setting without replacing human care. The goal is to provide a warm conversational experience for elders while giving caregivers a structured way to manage family context, review interactions, and respond to potential safety risks.

## Problem Statement

General-purpose chatbots are not enough for elder care scenarios because they usually:

- Do not understand the elder's personal history, preferences, family context, or health notes.
- Cannot role-play as familiar family members with consistent tone and shared memories.
- Do not provide caregiver-friendly tools for profile setup and monitoring.
- Do not distinguish normal conversation from urgent safety signals.
- Often fail hard when external AI, database, or TTS services are unavailable.

AI Care U addresses these issues through persona-based companionship, profile-grounded memory, safety-aware conversation, and demo-resilient fallback behavior.

## Design Goals

- **Elder-first interaction**: The elder UI should be simple, calm, and readable for older users.
- **Caregiver-friendly administration**: The admin dashboard should feel professional, clear, and usable by non-CS caregivers.
- **Family-persona companionship**: Each elder can talk with companion personas modeled after family roles.
- **Safety-aware conversation**: The system should detect distress, physical danger, and repeated negative emotional trends.
- **Demo resilience**: The project should still run in a basic mode without PostgreSQL, Gemini, Tavily, XTTS, or GPU.
- **Privacy-conscious media handling**: Uploaded voice samples and family/persona photos are treated as sensitive local data.

## Current Demo Scope

- 3 demo elder profiles: `W001`, `C001`, and `L001`
- 4 companion personas for each elder
- Elder-friendly frontend chat experience with an AI guide and family companion selection
- Caregiver-facing admin dashboard
- Admin upload for companion persona photos
- Admin upload for companion persona `.wav` voice samples
- TTS priority order: XTTS first, edge-tts fallback, Windows SAPI offline last-resort fallback
- iSafe emotion and safety monitoring
- Caregiver-assisted public background search and biography drafting
- Agent activity monitoring and conversation history review, filtered by elder profile
- Caregiver-visible admin identity, active session management, memory retrieval checks, and STT verification tools
- Demo mode that can run without Gemini, PostgreSQL, Tavily, XTTS, or GPU

## Out of Current Scope

The following features are intentionally excluded from the current demo scope:

- Aromatherapy RAG
- Face or facial emotion detection
- YOLO visual detection
- Hardware patrol, tracking, or positioning

This keeps the project focused on the features that are currently demonstrable: elder conversation, family personas, caregiver setup, TTS, safety monitoring, and admin review.

## System Overview

```text
Elder Chat UI
  -> FastAPI Backend
      -> Decision Agent
          -> MagicAI: persona-aware conversation
          -> iSafe: emotion and safety monitoring
          -> Memory Store: JSON first, optional PostgreSQL + pgvector
          -> TTS Service: XTTS -> edge-tts -> Windows SAPI
          -> Optional Tools: image generation, health-topic search

Caregiver Admin UI
  -> Profile management
  -> Persona management
  -> Voice/photo upload
  -> Public background candidates and biography drafts
  -> Conversation history
  -> iSafe and Decision monitoring
  -> Agent logs filtered by elder
  -> Session, memory retrieval, and STT verification tools
```

## Agent Architecture

### MagicAI

MagicAI is the conversation agent. It builds responses using the elder profile, active companion persona, family notes, biography, recent memories, and optional retrieved context. Its role is to make the conversation feel personal and emotionally appropriate.

### iSafe

iSafe monitors the elder's message for emotional state and safety risk. It identifies normal, positive, comfort-seeking, urgent, or emergency-like messages, and produces escalation signals that can be shown to caregivers.

Example safety demo sentence:

```text
I feel very dizzy and might fall.
```

### Decision

Decision is the orchestration layer. It coordinates iSafe, MagicAI, memory updates, optional image generation, optional health search, TTS selection, and agent logging. It is the backend layer that decides which system components should run for each interaction.

## Key User Flows

### Elder Starts a Conversation

1. The elder opens the chat interface.
2. The system loads the selected elder profile and active companion persona.
3. The elder sends text or voice input.
4. iSafe analyzes emotional and safety signals.
5. MagicAI generates a persona-aware response.
6. TTS plays the response using XTTS if a voice sample is available.

### Caregiver Creates or Updates a Profile

1. The caregiver opens the admin dashboard.
2. The caregiver selects an elder.
3. Basic profile fields, hobbies, sensitivity notes, diet notes, and biography can be reviewed or edited.
4. Family-provided notes can be added to improve future conversations.

### Caregiver Manages Companion Personas

1. The caregiver selects an elder in the persona management page.
2. The caregiver adds or edits companion personas such as daughter, son, spouse, or grandchild.
3. The caregiver can upload a persona photo.
4. The caregiver can upload a `.wav` voice sample for XTTS voice cloning.
5. The caregiver can generate a biography draft from basic profile fields and optional public sources.
6. The elder chooses the active companion from the elder-facing chat UI.

### Caregiver Reviews Safety Events

1. The elder sends a message that may indicate distress or danger.
2. iSafe classifies the safety level.
3. The event is stored in the profile history.
4. The caregiver reviews the event in the admin dashboard.

## Demo Dataset

| Elder ID | Name | Demo Focus |
|---|---|---|
| `W001` | Wang Daming | Retired engineer, Teresa Teng, chess, safety-alert demo |
| `C001` | Chen Xiuying | Retired teacher, gardening, cooking, family companionship |
| `L001` | Lin Yueqin | Former tailor, mild dementia care scenario |

Each elder should keep exactly 4 companion personas for the current professor-facing requirement.

## Project Structure

```text
Care4U_codex/
  backend/
    main.py                  FastAPI app and API routes
    agents/
      decision.py            Orchestrates MagicAI, iSafe, image, and health tools
      magic_ai.py            Persona-aware conversation agent
      i_safe.py              Emotion, safety, escalation, and trend monitoring
    services/
      llm_service.py         Gemini integration and demo fallback
      stt_service.py         Whisper and Breeze ASR speech recognition
      tts_service.py         XTTS, edge-tts, and Windows SAPI fallback
      embedding_service.py   Gemini embedding and demo fallback
    memory/
      json_store.py          JSON profile and event storage
      vector_store.py        Optional PostgreSQL + pgvector storage
    tools/
      health_search.py       Health-topic search support
      image_gen.py           Nostalgic image generation
      search_service.py      Biography and search support
    data/elders/             Demo elder JSON profiles
  frontend/
    index.html               Elder-facing chat UI
    admin.html               Caregiver admin dashboard
    app.js                   Frontend interaction logic
    avatars/                 Curated demo avatar assets
  demo_script.md             Demo walkthrough
  delivery_status.md         Delivery checklist and remaining work
  future_plan.md             Future improvement plan
```

## Quick Start

### 1. Install Dependencies

```powershell
pip install -r requirements.txt
```

On this Windows environment, if `python` or `py` is unavailable, use:

```powershell
C:\Users\user\bin\py.cmd
```

### 2. Configure Environment

Copy `.env.example` to `.env`.

For local demo mode, the important values are:

```env
CARE4U_DEMO_MODE=true
DB_ENABLED=false
STT_POOL_SIZE=1
XTTS_URL=http://localhost:8082
```

### 3. Start the Backend

```powershell
C:\Users\user\bin\py.cmd -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The elder PIN and bearer-token store is in process memory. Run one Uvicorn
worker for the current demo deployment; multiple workers do not share elder
sessions. Configure `ALLOWED_ELDER_IDS` to control which profiles may log in.

Or with a normal Python command:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 4. Open the App

- Elder UI: `http://127.0.0.1:8000/`
- Caregiver admin: `http://127.0.0.1:8000/admin`

## XTTS Voice Cloning

AI Care U uses XTTS first when the active companion persona has a `voice_path`.

Voice samples are uploaded from the admin dashboard as `.wav` files. If no voice sample is available, or if XTTS is unavailable, the system falls back to edge-tts. If edge-tts also fails in the local Windows demo environment, the system uses Windows SAPI as an offline last-resort fallback so the TTS API does not fail during a presentation.

Default XTTS endpoint:

```env
XTTS_URL=http://localhost:8082
```

Before the final demo, prepare and upload `.wav` samples for the companion personas that need XTTS voice cloning.

## Environment Variables

| Variable | Suggested Value | Purpose |
|---|---|---|
| `CARE4U_DEMO_MODE` | `true` | Enables fallback behavior when external services are unavailable |
| `GEMINI_API_KEY` | empty or real key | Gemini chat, summaries, image generation, and embeddings |
| `TAVILY_API_KEY` | empty or real key | Biography and health-topic search |
| `DB_ENABLED` | `false` | Enables or disables PostgreSQL / pgvector |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5433` | PostgreSQL port |
| `DB_NAME` | `aicaeru` | PostgreSQL database |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | empty | PostgreSQL password |
| `STT_POOL_SIZE` | `1` | Concurrent STT workers; use up to N for N simultaneous speakers only when memory permits |
| `STT_MODEL_SIZE` | `medium` | Whisper model size |
| `STT_DEVICE` | `cuda` or `cpu` | STT device |
| `XTTS_URL` | `http://localhost:8082` | Primary XTTS API endpoint |
| `BREEZYVOICE_URL` | `http://localhost:8080` | Legacy voice service endpoint |
| `LUXTTS_URL` | `http://localhost:8081` | Optional voice service endpoint |
| `ADMIN_USERNAME` | `admin` | Optional caregiver dashboard username |
| `ADMIN_PASSWORD` | empty | Enables Basic Auth for `/admin` when set |
| `ADMIN_ROLE` | `admin` | Role for the simple `ADMIN_USERNAME` / `ADMIN_PASSWORD` pair |
| `ADMIN_USERS` | empty | Optional JSON map for multiple admin users and roles |

Role-based admin access supports three roles:

- `viewer`: can read profiles/personas.
- `caregiver`: can read and update care data.
- `admin`: can manage sessions and perform caregiver actions.

Example `ADMIN_USERS`:

```json
{
  "caregiver1": {"password": "change-me", "role": "caregiver"},
  "supervisor": {"password": "change-me-too", "role": "admin"}
}
```

## PostgreSQL Schema and Indexing

When `DB_ENABLED=true`, initialize PostgreSQL and pgvector with:

```powershell
psql -d aicaeru -f backend/data/schema.sql
```

The schema includes the B-tree indexes used by the current elder, importance,
and recency filters. It intentionally does not create an HNSW index by default.
For a small demo dataset, an approximate vector index adds build and maintenance
cost without a meaningful query benefit. Consider HNSW only after memory volume
and latency grow, then compare representative retrieval queries with
`EXPLAIN ANALYZE` before and after adding the index.

## Safety, Privacy, and Ethics

AI Care U is intended as a supportive companion and caregiver-assistance tool. It is not a replacement for professional medical judgment or human caregiving.

Important boundaries:

- High-risk safety messages should be escalated to caregivers.
- Uploaded voice samples may contain biometric data and should remain local.
- Uploaded family/persona photos should remain local.
- The admin dashboard supports optional Basic Auth. Set `ADMIN_PASSWORD` to enable it.
- Deceased or sensitive family personas should be used with caution, especially for elders with cognitive impairment.

## Demo Checklist

1. Open the caregiver admin page.
2. Confirm all 3 elders exist.
3. Confirm each elder has 4 companion personas.
4. Upload companion persona photos and `.wav` samples if needed.
5. Open the elder chat UI.
6. Open the prepared elder chat session and choose a companion persona.
7. Test the safety sentence: "I feel very dizzy and might fall."
8. Review safety events, conversation history, and elder-filtered Agent logs in the admin dashboard.
9. Open memory retrieval and STT verification pages to confirm next-stage tools are available.
10. Run through `demo_script.md` once before the final presentation.

## Taiwanese STT Verification

The backend exposes a lightweight diagnostic endpoint:

```text
GET /api/stt/status
```

It reports whether Whisper, Torch, Transformers, ffmpeg, and the local Breeze ASR 26 cache are available. The admin dashboard includes a STT verification page for checking the route, uploading a real audio sample, and evaluating prepared transcripts with character error rate. Live transcription quality should still be checked with real Taiwanese audio before making it a primary presentation feature.

The latest verification record is documented in `stt_verification.md`.

## Evaluation Utilities

The next-stage evaluation endpoints are available behind admin access:

- `GET /api/admin/sessions`: inspect active elder/persona sessions.
- `POST /api/admin/sessions/clear`: clear a specific session or all sessions.
- `POST /api/admin/rag/evaluate`: run memory retrieval checks with prepared query/expected-term pairs.
- `POST /api/admin/stt/evaluate-transcripts`: evaluate prepared STT transcripts with character error rate.

The caregiver admin dashboard now exposes these utilities as UI pages, so they can be demonstrated without manually calling the API. On the current Windows-only demo run, memory retrieval uses local profile data when the Linux PostgreSQL / pgvector service is not started. When the Linux database service is running, the same evaluation flow can be used to compare database-backed retrieval results.

## Poster Draft

Poster content and architecture notes are drafted in `poster_content_draft.md`.

## Development Notes

- STT is lazy-loaded. FastAPI startup does not immediately load Whisper.
- Each STT worker loads its own model instance. For N elders speaking at the same time, `STT_POOL_SIZE=N` avoids queueing, but Whisper `medium` needs roughly 5 GB of GPU memory per worker before runtime and Breeze ASR overhead. Keep the pool at `1` for the demo or whenever GPU/CPU memory is limited; requests will queue instead of exhausting memory.
- PostgreSQL is optional. When `DB_ENABLED=false`, profile and event data use JSON files.
- Demo fallback behavior is important because capstone presentations often run in unstable local environments.
- `delivery_status.md` is the source of truth for current delivery status and remaining work.

## Future Work

- Expand memory retrieval evaluation with real caregiver/elder scenarios and poster-ready metrics.
- Add richer caregiver analytics for emotion trends and safety history.
- Prepare authorized `.wav` voice samples for XTTS voice cloning.
- Improve multi-elder session isolation for real deployment.
- Expand Taiwanese language support.
- Add deployment packaging such as Docker Compose.
