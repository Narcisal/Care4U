# AI Care U

AI Care U is a National Cheng Kung University Computer Science capstone project for AI-assisted elder companionship and caregiver support.

The project has two main surfaces:

- An elder-facing chat interface designed for simple, warm conversation.
- A caregiver admin dashboard for profile setup, family companion personas, safety review, and demo operation.

## Current Demo Scope

- 3 demo elder profiles: `W001`, `C001`, and `L001`
- 4 companion personas for each elder
- Elder-friendly frontend chat experience
- Caregiver-facing admin dashboard
- Admin upload for companion persona photos
- Admin upload for companion persona `.wav` voice samples
- TTS priority order: XTTS first, edge-tts fallback, Windows SAPI offline last-resort fallback
- iSafe emotion and safety monitoring
- Decision demo schedule controls
- Agent activity monitoring and conversation history review
- Demo mode that can run without Gemini, PostgreSQL, Tavily, XTTS, or GPU

Out of current scope:

- Aromatherapy RAG
- Face or facial emotion detection
- YOLO visual detection
- Hardware patrol, tracking, or positioning

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

## Demo Elders

| Elder ID | Name | Demo Focus |
|---|---|---|
| `W001` | Wang Daming | Retired engineer, Teresa Teng, chess, safety-alert demo |
| `C001` | Chen Xiuying | Retired teacher, gardening, cooking, family companionship |
| `L001` | Lin Yueqin | Former tailor, mild dementia care scenario |

Each elder should keep exactly 4 companion personas for the current professor-facing requirement.

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
| `STT_POOL_SIZE` | `1` | Whisper worker count; 1 is recommended for demo |
| `STT_MODEL_SIZE` | `medium` | Whisper model size |
| `STT_DEVICE` | `cuda` or `cpu` | STT device |
| `XTTS_URL` | `http://localhost:8082` | Primary XTTS API endpoint |
| `BREEZYVOICE_URL` | `http://localhost:8080` | Legacy voice service endpoint |
| `LUXTTS_URL` | `http://localhost:8081` | Optional voice service endpoint |

## Demo Checklist

1. Open the caregiver admin page.
2. Confirm all 3 elders exist.
3. Confirm each elder has 4 companion personas.
4. Upload companion persona photos and `.wav` samples if needed.
5. Open the elder chat UI.
6. Select an elder and start a chat session.
7. Test the safety sentence: "I feel very dizzy and might fall."
8. Review iSafe, conversation history, and Agent logs in the admin dashboard.
9. Run through `demo_script.md` once before the final presentation.

## Development Notes

- STT is lazy-loaded. FastAPI startup does not immediately load Whisper.
- PostgreSQL is optional. When `DB_ENABLED=false`, profile and event data use JSON files.
- Uploaded voice samples may contain biometric data and should not be committed.
- Uploaded family/persona photos should not be committed.
- `delivery_status.md` is the source of truth for current delivery status and remaining work.
