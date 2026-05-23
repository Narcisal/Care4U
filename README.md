<<<<<<< HEAD
# Care4U — AI-Powered Elderly Care Companion System

**Care4U** is an AI-driven conversational companion system designed for elderly users in long-term care settings. It supports voice dialogue, emotion-aware responses, multi-persona role-playing, and real-time safety monitoring. The system is built as a capstone project at the **Institute of Computer Science and Information Engineering, National Cheng Kung University (NCKU)**.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Installation and Setup](#installation-and-setup)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Known Limitations](#known-limitations)
- [Future Work](#future-work)

---

## Project Overview

Elderly individuals in long-term care often experience isolation, cognitive decline, and emotional distress. Care4U addresses this by providing a persistent AI companion that can:

- Hold natural Mandarin and Taiwanese (Taigi) voice conversations
- Remember the elder's life history, preferences, and past conversations
- Simulate the voice and personality of family members, including deceased loved ones
- Detect emotional distress and physical emergencies in real time
- Alert caregivers when escalation is warranted

The primary users are **elderly residents** of care facilities and the **caregivers and family members** who manage their care. The caregiver-facing admin panel allows profiles, personas, family notes, and biographies to be maintained without touching any code.

---

## Key Features

### Conversational AI

- Powered by **Google Gemini 2.5 Flash** with a contextual system prompt built from the elder's profile, biography, memory summaries, and long-term event records.
- Response priorities enforce safety first, then emotional support, then health reminders, then general companionship.
- Conversation history is maintained in session memory (up to 50 turns).

### Multi-Persona Role-Playing

- The admin can configure named personas (e.g., a daughter, a deceased spouse) with individual speaking styles, language preferences, shared memories, and forbidden topics.
- Two special modes for deceased personas: a soul-across-time mode for cognitively intact elders, and a gentle companion mode for elders with dementia.
- Each persona can optionally use a cloned voice via BreezyVoice.

### Voice I/O

- **Speech-to-Text**: Faster Whisper (medium model) for Mandarin; Breeze ASR 26 (MediaTek Research) for Taiwanese (Taigi). A pool of three concurrent STT workers handles overlapping requests.
- **Text-to-Speech**: Microsoft Edge-TTS with emotion-adjusted prosody (rate, pitch, volume). Optional BreezyVoice integration for voice cloning from a short audio sample.
- Speech rate is measured after transcription to detect unusually fast or slow speech, which feeds into emotion analysis.

### Memory System

- **Short-term**: Recent conversation events are appended to the elder's JSON profile (capped at 50 entries).
- **Long-term**: Events with importance >= 0.7 are stored in PostgreSQL with pgvector embeddings (768-dimensional Gemini embeddings). Semantic similarity search surfaces contextually relevant memories during each chat turn.
- **Biography**: A narrative life-history document is auto-generated on profile creation (via Tavily web search and Gemini) and updated every 10 conversation turns by merging new high-importance events.
- **Memory summaries**: Every 10 turns the system condenses recent events into a short paragraph for caregiver review.

### Safety Monitoring (iSafe Agent)

- LLM-based emotion analysis classifies each message as `urgent`, `comfort`, `happy`, or `normal`, with a continuous emotion score from -1.0 to 1.0.
- Four escalation levels:
  - **Level 0** — Normal; AI handles alone.
  - **Level 1** — Concern (e.g., mild sadness); AI comforts, backend logs alert.
  - **Level 2** — Urgent (e.g., dizziness, expressed severe pain); notify caregiver.
  - **Level 3** — Emergency (e.g., fall, chest pain, loss of consciousness); immediate intervention required.
- Trend detection: three consecutive negative emotions trigger a caregiver-facing trend alert.
- Taiwan-specific language understanding: Hokkien medical terms and common elder speech patterns are handled explicitly in the analysis prompt.

### Contextual Image Generation

- When an elder describes a visual memory (a specific place, object, or scene), Gemini 2.5 Flash Image generates a warm, nostalgic watercolor/oil-painting illustration.
- Strict generation constraints: no human faces, no modern technology, no text.
- The image is returned as a base64 data URI and displayed directly in the chat interface.

### Health Information Search

- Detects health-related topics in the elder's messages (rehabilitation, medication, diet, blood pressure, diabetes, dementia, fall prevention, sleep).
- Retrieves relevant Taiwan health education content via Tavily and displays it as an information card alongside the AI response.

### Caregiver Admin Panel

- Manage elder profiles: name, gender, former occupation, hobbies, health notes, cognitive status.
- Add, edit, and delete AI personas with voice sample upload.
- View, add, and delete family notes that are injected into the AI's context.
- Manual biography editing with auto-refresh on next session.

---

## System Architecture

```
Care4U/
├── backend/
│   ├── main.py                  # FastAPI application, all HTTP endpoints
│   ├── agents/
│   │   ├── decision.py          # Orchestrator: coordinates iSafe, MagicAI, tools
│   │   ├── magic_ai.py          # Conversational agent with memory integration
│   │   └── i_safe.py            # Safety and emotion analysis agent
│   ├── services/
│   │   ├── llm_service.py       # All Gemini LLM calls (chat, emotion, summaries, bios)
│   │   ├── stt_service.py       # Whisper + Breeze ASR speech recognition
│   │   ├── tts_service.py       # Edge-TTS + BreezyVoice speech synthesis
│   │   └── embedding_service.py # Gemini text embeddings
│   ├── memory/
│   │   ├── memory_manager.py    # Abstract base class
│   │   ├── json_store.py        # JSON file storage for profiles and events
│   │   └── vector_store.py      # PostgreSQL/pgvector storage and semantic search
│   ├── tools/
│   │   ├── search_service.py    # Tavily web search, biography generation
│   │   ├── health_search.py     # Health topic detection and content retrieval
│   │   └── image_gen.py         # Gemini image generation
│   └── data/
│       └── elders/              # One JSON file per elder (e.g., W001.json)
└── frontend/
    ├── index.html               # Elder-facing conversation interface
    ├── admin.html               # Caregiver admin panel
    └── app.js                   # Frontend logic: voice recording, API calls, UI
```

### Request Flow

```
Browser (voice or text input)
  |
  | POST /api/stt      audio -> text + speech rate measurement
  |
  v
Decision.chat()
  |
  +-- iSafe.analyze()        emotion label, escalation level, trend alerts
  +-- MagicAI.chat()         Gemini response with full memory context
  +-- detect_image_trigger() optional nostalgic image (Gemini image generation)
  +-- detect_health_topic()  optional health information card (Tavily)
  |
  v
JSON response returned to browser
  |
  | POST /api/tts      text -> audio with emotion-adjusted prosody
  |
  v
Audio playback in browser
```

### Memory Write Path

```
ISafe._save_event()
  |
  +-- JsonMemoryStore.add_event()    append to elder JSON file (immediate)
  +-- VectorMemoryStore.add_event()  INSERT into elder_memories (PostgreSQL)
        |
        +-- EmbeddingService.embed()  UPDATE embedding column (pgvector, async)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI 0.135, Uvicorn 0.44 |
| LLM | Google Gemini 2.5 Flash (`gemini-2.5-flash`) |
| Embeddings | Google Gemini Embedding-2, 768 dimensions |
| Image generation | Google Gemini 2.5 Flash Image (`gemini-2.5-flash-image`) |
| Speech-to-text (Mandarin) | Faster Whisper 1.2, medium model |
| Speech-to-text (Taiwanese) | Breeze ASR 26 (MediaTek Research, via HuggingFace) |
| Text-to-speech | Edge-TTS 7.2; BreezyVoice (optional, external server) |
| Vector database | PostgreSQL 14+ with pgvector extension |
| Profile storage | JSON files, one per elder |
| Web search | Tavily Python SDK 0.7 |
| ML runtime | PyTorch 2.7 (CUDA 11.8 build; CPU fallback supported) |
| Transformer models | HuggingFace Transformers 5.8 |
| Audio processing | soundfile, torchaudio, imageio-ffmpeg |
| Frontend | Vanilla HTML5 / CSS3 / JavaScript, no framework |
| Data validation | Pydantic v2 |
| Environment config | python-dotenv |

---

## Installation and Setup
=======
# AI Care U

An AI-powered elderly care companion system built as a capstone project at National Cheng Kung University (NCKU), Department of Computer Science.

---

## Project Overview

AI Care U addresses the growing challenge of social isolation and cognitive decline among elderly individuals in Taiwan. The system provides a voice-first conversational companion that can simulate the presence of family members, monitor emotional states, and alert caregivers when intervention is needed.

The system is designed for elderly users who may have varying degrees of cognitive decline. It supports natural spoken interaction in both Mandarin and Taiwanese Mandarin, maintains long-term memory of the user's life history, and adapts its communication style to the individual's profile and current emotional state. A separate caregiver dashboard allows family members or care staff to configure the system, review conversation history, and monitor safety alerts.

---

## Key Features

**Personalized Conversational AI**
Conversations are driven by a per-elder profile that includes biographical information, health notes, cognitive status, and personal preferences. The LLM uses this context to produce responses that feel appropriate for the individual.

**Virtual Family Member Personas**
Caregivers can configure personas that represent family members (son, daughter, grandchild, etc.). The system role-plays as these personas during conversation, including ethical-mode simulation for deceased relatives. Each persona has its own voice, language style, personality traits, and shared memories. Voice cloning from uploaded audio samples is supported via BreezyVoice.

**Multi-language Speech Recognition**
Speech-to-text supports standard Mandarin (via Faster Whisper) and Taiwan dialect/mixed Mandarin-Taiwanese (via Breeze ASR 26 by MediaTek). The caregiver can switch the language mode from the dashboard.

**Emotion-Aware Response and TTS**
The iSafe agent classifies the emotional tone of each message and adjusts TTS output accordingly (normal, happy, comfort, urgent, sad). Speech rate is also analyzed to detect urgency. If negative emotional trends persist over consecutive turns, escalation alerts are generated for caregivers.

**Three-Agent Orchestration**
Backend logic is split across three cooperating agents:
- **MagicAI** — generates conversation responses using persona context and retrieved memories
- **iSafe** — performs emotion analysis, safety monitoring, and escalation management
- **Decision** — routes messages, triggers conditional features (image generation, health search, biography updates), and logs agent activity

**Vector Memory with Long-term Persistence**
Significant conversational events are embedded and stored in a PostgreSQL database with the pgvector extension. Semantically similar memories are retrieved at inference time to make responses contextually grounded. A JSON file serves as a fallback store when the database is unavailable.

**Nostalgic Image Generation**
When the LLM detects that the elder is describing a nostalgic scene, it triggers Gemini image generation to display a relevant vintage Taiwan-themed illustration in the chat interface.

**Auto-Biography Generation**
On first setup, the system performs a Tavily web search for publicly available information about the elder and uses the LLM to compose a biographical summary. Caregivers can manually review and edit this biography.

**Caregiver Dashboard**
A web-based admin panel provides profile management, persona configuration, conversation history, iSafe safety status, Decision SOP logs, and real-time agent activity monitoring.

---

## System Architecture

```
Browser (Elder UI)              Browser (Caregiver Dashboard)
       |                                      |
       +------------------+-------------------+
                          |
                    FastAPI Backend
                          |
          +---------------+---------------+
          |               |               |
       Decision         iSafe          MagicAI
       (Orchestrator)  (Emotion)      (Conversation)
          |               |               |
          +-------+-------+-------+-------+
                  |               |
          LLM Service         Memory Layer
          (Gemini 2.5)     +---+---+
                           |       |
                      pgvector   JSON
                      (long-term) (backup)
                           |
                  Supporting Services
              STT | TTS | Search | ImageGen
```

The backend is a single FastAPI application. On startup it initializes a pool of STT worker instances and loads elder profiles from disk. The three agents are instantiated per-elder and cached in memory. The frontend is static HTML and vanilla JavaScript served directly by FastAPI.

External services that must be running independently:
- PostgreSQL with pgvector (vector memory storage)
- XTTS server (for XTTS-based TTS, must be started before the main backend)

---

## Tech Stack

**Backend**
- Python 3.10+
- FastAPI 0.135 / Uvicorn 0.44
- Pydantic 2.12

**AI / ML**
- Google Gemini 2.5 Flash — LLM (chat, emotion analysis, biography generation, image generation)
- Gemini Embedding v2 — 768-dimensional text embeddings
- Faster Whisper (medium model) — Mandarin speech recognition
- Breeze ASR 26 (MediaTek) — Taiwan dialect / mixed-language ASR
- Edge-TTS 7.2 — default text-to-speech (Microsoft)
- BreezyVoice — voice cloning from uploaded audio sample
- XTTS v2 — cross-lingual voice synthesis (external server)
- PyTorch 2.7 (CUDA 11.8)

**Data Storage**
- PostgreSQL 13+ with pgvector extension
- JSON files for elder profiles and conversation backup

**Search**
- Tavily Python SDK — web search for elder background research

**Frontend**
- Vanilla HTML5 + JavaScript
- Tailwind CSS (admin dashboard)

**Key Python Libraries**
- `google-genai` 1.70
- `faster-whisper` 1.2
- `transformers` 5.8 (Breeze ASR tokenizer)
- `edge-tts` 7.2
- `pgvector` 0.4
- `psycopg2-binary` 2.9
- `av` 17.0 (audio processing)
- `python-dotenv` 1.2

---

## Project Structure

```
Care4U/
├── backend/
│   ├── main.py                  # FastAPI application, all route handlers
│   ├── agents/
│   │   ├── magic_ai.py          # MagicAI: response generation with memory retrieval
│   │   ├── i_safe.py            # iSafe: emotion analysis and safety monitoring
│   │   └── decision.py          # Decision: orchestration, logging, feature triggers
│   ├── services/
│   │   ├── llm_service.py       # Gemini LLM wrapper and system prompt construction
│   │   ├── stt_service.py       # STT pool (Faster Whisper + Breeze ASR)
│   │   ├── tts_service.py       # Multi-engine TTS with emotion pacing
│   │   └── embedding_service.py # Gemini embedding generation
│   ├── memory/
│   │   ├── memory_manager.py    # Abstract base class for memory stores
│   │   ├── vector_store.py      # PostgreSQL + pgvector implementation
│   │   └── json_store.py        # JSON file fallback implementation
│   ├── tools/
│   │   ├── search_service.py    # Tavily search + LLM biography generation
│   │   ├── image_gen.py         # Nostalgic scene image generation via Gemini
│   │   └── health_search.py     # Health information retrieval (placeholder)
│   └── data/
│       └── elders/              # Per-elder JSON profile and conversation files
├── frontend/
│   ├── index.html               # Elder conversation interface
│   ├── admin.html               # Caregiver dashboard
│   ├── app.js                   # Frontend logic for both interfaces
│   └── avatars/                 # Avatar PNG assets (elder, family, AI personas)
├── requirements.txt
├── .env.example
└── future_plan.md
```

---

## Installation & Setup
>>>>>>> cf18642f1d870ffb03738fbf26c88ef7630945f0

### Prerequisites

- Python 3.10 or higher
<<<<<<< HEAD
- FFmpeg (bundled automatically via `imageio-ffmpeg`; no manual install needed)
- PostgreSQL 14+ with the `pgvector` extension installed
- An NVIDIA GPU is recommended for Whisper inference; CPU fallback is supported but significantly slower
- A BreezyVoice server is optional and only required for voice cloning personas

### 1. Clone the repository

```bash
git clone <repository-url>
cd Care4U
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 3. Install Python dependencies
=======
- PostgreSQL 13+ with the `pgvector` extension installed
- An NVIDIA GPU is recommended; CPU fallback is supported but significantly slower for STT
- FFmpeg (installed automatically via `imageio-ffmpeg` if not already present)

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Care4U
```

### 2. Create a Python Virtual Environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

### 3. Install Python Dependencies
>>>>>>> cf18642f1d870ffb03738fbf26c88ef7630945f0

```bash
pip install -r requirements.txt
```

<<<<<<< HEAD
> **Note on PyTorch:** `requirements.txt` pins `torch==2.7.1+cu118` for CUDA 11.8. If you are on CPU only or a different CUDA version, install the correct PyTorch build from [pytorch.org](https://pytorch.org/get-started/locally/) before running the above command, then re-run `pip install -r requirements.txt`.

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your API keys and database credentials
```

See the [Configuration](#configuration) section for all variables.

### 5. Set up PostgreSQL

Connect to your PostgreSQL instance and run the following:

```sql
CREATE DATABASE aicaeru;
\c aicaeru

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE elder_memories (
    id          SERIAL PRIMARY KEY,
    elder_id    TEXT NOT NULL,
    content     TEXT,
    sentiment   TEXT,
    importance  FLOAT,
    memory_type TEXT,
    topic_tags  TEXT[],
    spoken_at   TIMESTAMP,
    date        DATE,
    persona_id  TEXT DEFAULT 'ai',
    embedding   VECTOR(768),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ON elder_memories USING ivfflat (embedding vector_cosine_ops);
```

> If you skip this step, the system will still run using JSON file storage only. Vector similarity search will be silently disabled.

### 6. Create an elder profile

Place a JSON file in `backend/data/elders/` using the naming convention `<ELDER_ID>.json`. See `backend/data/elders/W001.json` for a complete example. The minimum required structure is:

```json
{
  "elder_id": "W001",
  "name": "Wang Daming",
  "gender": "male",
  "cognitive_status": "normal",
  "persona": {
    "former_job": "Engineer",
    "tone_preference": "friendly",
    "hobbies": ["chess", "music"]
  },
  "health_notes": {
    "sensitivity": ["cold weather"],
    "diet": "prefers hot drinks"
  },
  "personas": {
    "ai": {
      "name": "AI Companion",
      "voice_engine": "edge",
      "honorific": "Grandpa"
    }
  },
  "active_persona": "ai",
  "recent_events": [],
  "memory_summary": {},
  "elder_biography": {},
  "biography_usage_count": 0,
  "family_notes": []
}
```

Profiles can also be created through the admin panel at `/admin`.

### 7. Start the server

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

- Elder conversation interface: `http://localhost:8000`
- Caregiver admin panel: `http://localhost:8000/admin`

---

## API Endpoints

All endpoints accept and return JSON unless noted otherwise.

### Conversation

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/greet` | Generate a time-aware greeting to open a session. Body: `{"elder_id": "W001"}` |
| `POST` | `/api/chat` | Send a text message. Returns response text, emotion label, escalation level, optional image (base64), and optional health card. Body: `{"elder_id": "W001", "message": "...", "speed_emotion": "normal"}` |
| `POST` | `/api/switch-elder` | Clear cached agent state so the next request loads a fresh profile. Body: `{"elder_id": "W001"}` |

### Speech I/O

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/stt` | Transcribe audio. Multipart form with an `audio` field (webm). Returns `text`, `speed_emotion`, `speech_rate`, `duration`. |
| `POST` | `/api/tts` | Synthesize speech. Body: `{"text": "...", "emotion": "normal"}`. Returns `audio/mpeg` binary. |
| `POST` | `/api/stt/language` | Switch recognition language for all pool workers. Body: `{"elder_id": "W001", "language": "zh"}`. Options: `zh` (Mandarin), `tai` (Taiwanese). |

### Profile Management

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/profile/{elder_id}` | Retrieve the full elder profile. |
| `POST` | `/api/profile/save` | Create or update basic profile fields (name, gender, occupation, hobbies, health notes, cognitive status). |
| `POST` | `/api/profile/save-biography` | Manually save biography text. Sets `manually_edited: true`, which prevents auto-updates. |
| `POST` | `/api/profile/search-background` | Trigger a Tavily web search and generate a biography. Body: `{"elder_id": "W001", "name": "...", "keywords": [...]}` |

### Persona Management

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/profile/{elder_id}/personas` | List all configured personas and the currently active persona ID. |
| `POST` | `/api/profile/persona/add` | Add a new persona. The speaking-style description is generated asynchronously in the background after the response is returned. |
| `POST` | `/api/profile/persona/delete` | Delete a persona by ID. The built-in `ai` persona cannot be deleted. |
| `POST` | `/api/profile/persona/switch` | Activate a persona. Resets the cached agent so the change takes effect on the next request. |
| `POST` | `/api/profile/persona/upload-voice` | Upload a WAV voice sample for BreezyVoice cloning. Multipart form: `elder_id`, `persona_id`, `voice` (file). |

### Family Notes

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/profile/family-note/add` | Append a caregiver note that will be injected into the AI's system prompt. Body: `{"elder_id": "W001", "note": "..."}` |
| `POST` | `/api/profile/family-note/delete` | Remove a note by its list index. Body: `{"elder_id": "W001", "index": 0}` |

### Monitoring

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/history/{elder_id}` | Retrieve the current in-session conversation history. |
| `GET` | `/api/safety/{elder_id}` | Retrieve aggregated safety counts: urgent events, negative events, trend alerts, and overall hazard level. |
| `GET` | `/api/agent-logs` | Retrieve the last 100 internal agent log entries for debugging. |

---

## Configuration

All configuration is provided through environment variables in a `.env` file at the project root.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Google AI Studio API key. Used for all LLM, embedding, and image generation calls. |
| `TAVILY_API_KEY` | No | — | Tavily search API key. Required for biography web search and health information lookup. If absent, these features are skipped gracefully. |
| `DB_HOST` | No | `localhost` | PostgreSQL host. |
| `DB_PORT` | No | `5433` | PostgreSQL port. |
| `DB_NAME` | No | `aicaeru` | PostgreSQL database name. |
| `DB_USER` | No | `postgres` | PostgreSQL username. |
| `DB_PASSWORD` | No | `careU1234` | PostgreSQL password. |
| `BREEZYVOICE_URL` | No | `http://localhost:8080` | Base URL of a BreezyVoice-compatible server (OpenAI audio API format). Only required when a persona is configured with `voice_engine: "breezyvoice"`. |

### Degraded-mode behavior

| Missing dependency | Effect |
|---|---|
| PostgreSQL unreachable | System continues with JSON storage only. Vector similarity search is disabled. |
| `TAVILY_API_KEY` absent | Biography web search returns empty. Health lookup returns empty. Conversation and safety are unaffected. |
| BreezyVoice server unreachable | TTS automatically falls back to Edge-TTS for the affected persona. |
| GPU unavailable | Whisper loads on CPU. Transcription is significantly slower (5-10x). |
| Breeze ASR 26 not yet downloaded | First switch to Taiwanese language mode triggers a ~1.5 GB download from HuggingFace Hub. Subsequent starts use the local model cache. |
=======
If you need a CUDA version other than 11.8, or a CPU-only install, install PyTorch manually before running the above command and remove the torch entries from `requirements.txt`.

### 4. Configure the Database

Start PostgreSQL and create the database and the pgvector extension:

```sql
CREATE DATABASE aicaeru;
\c aicaeru
CREATE EXTENSION IF NOT EXISTS vector;
```

The application creates the `elder_memories` table automatically on first startup.

### 5. Configure Environment Variables

Copy `.env.example` to `.env` and fill in all required values:

```bash
cp .env.example .env
```

See the [Environment Variables](#environment-variables) section below for the full list of required fields.

### 6. Start the XTTS Server

**The XTTS voice server must be started before the main FastAPI backend.** If it is not running, any persona configured to use the XTTS engine will fail when TTS is requested.

Follow the setup instructions for your XTTS v2 installation and start it on the port you configured in `.env`. If you are not using XTTS-based voices and only need Edge-TTS or BreezyVoice, this step can be skipped.

### 7. Start the Main Backend

```bash
# Development (with hot-reload)
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# Production
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 8. Open the Application

- Elder conversation interface: `http://127.0.0.1:8000/`
- Caregiver dashboard: `http://127.0.0.1:8000/admin`

---

## Environment Variables

All variables are read from `.env` in the project root at startup.

| Variable | Description | Example |
|---|---|---|
| `GEMINI_API_KEY` | Google AI API key (Gemini LLM, embeddings, image generation) | `AIza...` |
| `TAVILY_API_KEY` | Tavily search API key for elder biography research | `tvly-...` |
| `DB_HOST` | PostgreSQL host address | `127.0.0.1` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_NAME` | Database name | `aicaeru` |
| `DB_USER` | Database username | `postgres` |
| `DB_PASSWORD` | Database password | `yourpassword` |
| `BREEZYVOICE_URL` | Base URL of the BreezyVoice / XTTS voice synthesis server | `http://localhost:8080` |

---

## API Endpoints

All endpoints are served by the FastAPI backend. Responses are JSON unless otherwise noted.

### Pages

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve elder conversation interface (HTML) |
| GET | `/admin` | Serve caregiver dashboard (HTML) |

### Conversation

| Method | Path | Description |
|---|---|---|
| POST | `/api/greet` | Generate a context-aware greeting for the active elder |
| POST | `/api/chat` | Process a user text message; returns AI response and emotion analysis |
| POST | `/api/stt` | Accept an audio file upload; return transcribed text |
| POST | `/api/tts` | Accept text and emotion label; return synthesized audio |
| POST | `/api/stt/language` | Switch STT language mode (`zh` for Mandarin, `tai` for Taiwan dialect) |

### Elder Profile

| Method | Path | Description |
|---|---|---|
| GET | `/api/profile/{elder_id}` | Retrieve the full elder profile |
| POST | `/api/profile/save` | Create or update elder basic information |
| POST | `/api/profile/search-background` | Trigger Tavily web search and LLM biography generation |
| POST | `/api/profile/save-biography` | Save a manually edited biography |
| POST | `/api/profile/family-note/add` | Add a caregiver note to the profile |
| POST | `/api/profile/family-note/delete` | Delete a caregiver note by index |

### Personas

| Method | Path | Description |
|---|---|---|
| GET | `/api/profile/{elder_id}/personas` | List all configured personas and the currently active one |
| POST | `/api/profile/persona/add` | Create a new persona (triggers LLM tone generation) |
| POST | `/api/profile/persona/delete` | Remove a persona |
| POST | `/api/profile/persona/switch` | Set a persona as active for subsequent conversations |
| POST | `/api/profile/persona/upload-voice` | Upload an audio sample for voice cloning |

### Monitoring

| Method | Path | Description |
|---|---|---|
| GET | `/api/history/{elder_id}` | Retrieve conversation history |
| GET | `/api/safety/{elder_id}` | Get iSafe safety status and current escalation level |
| GET | `/api/agent-logs` | Retrieve the last 100 agent activity log entries |
| POST | `/api/switch-elder` | Switch the active elder context and clear the agent cache |
>>>>>>> cf18642f1d870ffb03738fbf26c88ef7630945f0

---

## Known Limitations

<<<<<<< HEAD
**Security**

- The `/admin` endpoint has no authentication. Any client that can reach the server URL can read and modify all elder profiles. This is acceptable for a local demo but must be addressed before any networked deployment.
- CORS is configured to allow all origins (`allow_origins=["*"]`). This should be restricted to the actual frontend origin in production.

**Concurrency**

- `VectorMemoryStore` holds a single `psycopg2` connection shared across all threads. Under concurrent load (multiple elders active simultaneously), this causes cursor contention. A connection pool such as `psycopg2.pool.ThreadedConnectionPool` or a migration to `asyncpg` is needed for multi-user deployment.

**State persistence**

- `MagicAI.conversation_history` lives in process memory only. Restarting the server clears all active session context. Elder profiles and PostgreSQL event records persist, but the within-session dialogue turns do not.

**Biography usage counter**

- `biography_usage_count` is intended to throttle how often the AI references biography information within a session. The counter is never incremented in the current code, so the LLM always receives the "first use" instruction regardless of how many turns have passed.

**Speech recognition accuracy**

- Faster Whisper medium provides good Mandarin accuracy but degrades with thick Taiwanese accents, mixed Mandarin/Taigi utterances, and quiet or noisy audio. The Taiwan-specific initial prompt improves recognition of common family vocabulary but does not eliminate substitution errors.

**Image generation reliability**

- Gemini image generation occasionally returns no image despite a successful API response. The system handles this gracefully by simply omitting the image, but there is no automatic retry for the image code path.

**Scalability**

- The system is designed and tested for a single active conversation on a single server. The three-worker STT pool and in-process agent caches do not scale horizontally without additional coordination.
=======
**GPU Memory Requirements**
Running Faster Whisper (medium) and Breeze ASR 26 simultaneously requires substantial VRAM. On low-VRAM or CPU-only systems, STT worker pool initialization is slow and transcription latency is high. Breeze ASR 26 is lazy-loaded on first use to avoid penalizing startup time when Taiwan dialect mode is not needed.

**XTTS Server Dependency**
XTTS-based TTS requires an external server process managed separately from the main backend. If that server is unavailable, personas configured to use the XTTS engine will produce errors. BreezyVoice and Edge-TTS are unaffected.

**No Authentication**
The caregiver dashboard at `/admin` is completely unprotected. CORS is configured to allow all origins (`*`). This is acceptable only on a local or isolated private network. Do not expose the server to the public internet without adding authentication.

**Single-Elder Active Session**
The active elder context is stored as global server state. Only one elder can be in an active session at a time across all connected clients. Switching elders via the dashboard clears the cached agent state for all sessions simultaneously.

**Windows Development Environment**
The project was developed and tested on Windows 11 with PowerShell. Some audio processing paths and path handling assume Windows conventions. Linux/macOS compatibility has not been fully verified.

**No Response Streaming**
LLM responses and TTS audio are generated as complete objects before being returned to the client. For long responses, there is a noticeable delay before the elder interface begins playback.

**Database Connection Pooling**
Database connections are opened per-request without a connection pool. Under concurrent load this may exhaust the PostgreSQL connection limit.
>>>>>>> cf18642f1d870ffb03738fbf26c88ef7630945f0

---

## Future Work

<<<<<<< HEAD
- **Authentication and access control**: Protect the admin panel with login credentials. Distinguish caregiver, family member, and supervisor roles with different permissions.
- **Real-time caregiver notification**: Replace the frontend polling the safety endpoint with WebSocket push or SMS/push notification delivery for Level 2 and Level 3 escalation events.
- **Streaming responses**: Use Server-Sent Events or WebSocket streaming to begin TTS audio playback before the full LLM response is received, reducing perceived latency.
- **Persistent session history**: Store conversation turns in PostgreSQL so sessions survive server restarts and can be reviewed historically by caregivers.
- **Biography usage counter**: Increment `biography_usage_count` after each conversation turn so the prompt instruction correctly prevents repetitive references to the same biographical details.
- **Connection pooling**: Replace the single synchronous `psycopg2` connection with a thread-safe pool to support multiple concurrent users safely.
- **Caregiver analytics dashboard**: A richer view showing emotion trends over time, conversation volume per day, and a timeline of safety events for each elder.
- **Multi-language TTS**: Extend voice output to cover Taiwanese-accented Mandarin voices and explore Hokkien TTS options as they become publicly available.
- **Mobile interface**: A tablet-optimised view for elders who are more comfortable interacting on a mobile device rather than a desktop browser.
- **Offline fallback**: A lightweight on-device model for core conversation functionality when internet connectivity is unreliable, which is common in rural long-term care facilities in Taiwan.
=======
The following improvements are identified in `future_plan.md`.

**Short-term**
- Importance scoring tuning for better long-term memory consolidation
- Nostalgic image generation quality improvements (style consistency, scene filtering)
- Aromatherapy device integration via RAG-based health recommendations

**Medium-term**
- Long-term memory summarization to prevent unbounded memory growth
- Audio prosody-based emotion detection independent of text content
- Expanded Taiwan dialect support beyond Breeze ASR 26

**Long-term**
- Pure voice mode (screenless operation) for users unable to operate a display
- Family video integration for visual persona simulation
- Multi-elder concurrent session support with proper session isolation
- Authentication and role-based access control for the caregiver dashboard
- Containerized deployment via Docker Compose

---

## Academic Context

This project was developed as a capstone (senior thesis) project at the Department of Computer Science, National Cheng Kung University (NCKU), Taiwan, in the 2025-2026 academic year.
>>>>>>> cf18642f1d870ffb03738fbf26c88ef7630945f0
