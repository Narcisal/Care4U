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

### Prerequisites

- Python 3.10 or higher
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

```bash
pip install -r requirements.txt
```

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

---

## Known Limitations

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

---

## Future Work

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
