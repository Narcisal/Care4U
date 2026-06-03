import asyncio
import json
import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import secrets

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agents.decision import Decision, clear_agent
from backend.services.tts_service import TTSService
from backend.memory.vector_store import VectorMemoryStore
from backend.services.embedding_service import EmbeddingService
from backend.services.llm_service import LLMService
from backend.tools.search_service import SearchService

app = FastAPI(title="AI Care U")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")
admin_security = HTTPBasic(auto_error=False)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_USERS = os.getenv("ADMIN_USERS", "")

# ------------------------------------------------------------------
# STT worker pool
# ------------------------------------------------------------------

STT_POOL_SIZE = int(os.getenv("STT_POOL_SIZE", "1"))
STT_MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "medium")
STT_DEVICE = os.getenv("STT_DEVICE", "cuda")
stt_pool: list[object] = []
stt_pool_lock: asyncio.Queue = asyncio.Queue()
stt_init_lock = asyncio.Lock()
tts = TTSService(voice="zh-TW-HsiaoChenNeural")
decisions: dict[str, Decision] = {}


@app.on_event("startup")
async def startup_event():
    print(f"STT worker pool 延遲初始化：size={STT_POOL_SIZE}, model={STT_MODEL_SIZE}, device={STT_DEVICE}")


async def ensure_stt_pool():
    if stt_pool:
        return

    async with stt_init_lock:
        if stt_pool:
            return

        try:
            from backend.services.stt_service import STTService

            workers = [
                STTService(model_size=STT_MODEL_SIZE, device=STT_DEVICE)
                for _ in range(STT_POOL_SIZE)
            ]
        except Exception as e:
            traceback.print_exc()
            print(f"STTService {STT_DEVICE} 初始化失敗，退回 CPU：{e}")
            from backend.services.stt_service import STTService

            workers = [
                STTService(model_size=STT_MODEL_SIZE, device="cpu")
                for _ in range(STT_POOL_SIZE)
            ]

        stt_pool.extend(workers)
        for worker in stt_pool:
            await stt_pool_lock.put(worker)
        print(f"STT worker pool 初始化完成，共 {len(stt_pool)} 個實例")


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    elder_id: str
    message: str
    speed_emotion: str = "normal"
    session_id: str = "default"
    persona_id: Optional[str] = None

class GreetRequest(BaseModel):
    elder_id: str
    session_id: str = "default"
    persona_id: Optional[str] = None

class TTSRequest(BaseModel):
    text: str
    emotion: str = "normal"
    elder_id: Optional[str] = None
    persona_id: Optional[str] = None

class ElderProfileUpdate(BaseModel):
    elder_id: str
    name: str
    gender: str
    former_job: str
    tone_preference: str
    hobbies: str
    sensitivity: str
    diet: str
    cognitive_status: str = "normal"

class BackgroundCandidateRequest(BaseModel):
    elder_id: str
    extra_keywords: list = []

class BiographyDraftRequest(BaseModel):
    elder_id: str
    selected_sources: list = []

class BiographyUpdateRequest(BaseModel):
    elder_id: str
    biography: str
    sources: list = []

class PersonaAddRequest(BaseModel):
    elder_id: str
    name: str
    relation: str
    honorific: str
    language: str = "mandarin"
    personality: list = []
    habits: list = []
    voice_engine: str = "xtts"
    voice_path: str = None
    is_deceased: bool = False
    shared_memories: str = ""
    current_status: str = ""
    forbidden_topics: str = ""

class PersonaDeleteRequest(BaseModel):
    elder_id: str
    persona_id: str

class PersonaSwitchRequest(BaseModel):
    elder_id: str
    persona_id: str

class LanguageRequest(BaseModel):
    elder_id: str
    language: str

class FamilyNoteRequest(BaseModel):
    elder_id: str
    note: str

class FamilyNoteDeleteRequest(BaseModel):
    elder_id: str
    index: int

class SessionClearRequest(BaseModel):
    elder_id: Optional[str] = None
    session_id: Optional[str] = None

class RAGEvaluationRequest(BaseModel):
    elder_id: str
    queries: list[dict]

class STTEvaluationRequest(BaseModel):
    samples: list[dict]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _load_admin_users() -> dict:
    """Load role users from ADMIN_USERS JSON or the simple ADMIN_* pair."""
    if ADMIN_USERS:
        try:
            data = json.loads(ADMIN_USERS)
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"ADMIN_USERS 解析失敗：{e}")
    if ADMIN_PASSWORD:
        return {
            ADMIN_USERNAME: {
                "password": ADMIN_PASSWORD,
                "role": os.getenv("ADMIN_ROLE", "admin"),
            }
        }
    return {}


def _authenticate_admin(credentials: HTTPBasicCredentials | None) -> dict | None:
    users = _load_admin_users()
    if not users:
        return {"username": "demo", "role": "admin"}
    if not credentials:
        return None
    user = users.get(credentials.username)
    if not user:
        return None
    expected_password = user.get("password", "")
    if not secrets.compare_digest(credentials.password, expected_password):
        return None
    return {"username": credentials.username, "role": user.get("role", "viewer")}


def require_admin_role(*allowed_roles: str):
    """Optional Basic Auth for the caregiver dashboard.

    Local demo mode remains frictionless when no admin password/users are set.
    Set ADMIN_PASSWORD for one admin, or ADMIN_USERS JSON for role-based access.
    """
    def dependency(credentials: HTTPBasicCredentials = Depends(admin_security)):
        user = _authenticate_admin(credentials)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Admin login required",
                headers={"WWW-Authenticate": "Basic"},
            )
        if allowed_roles and user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient admin role")
        return user
    return dependency


require_admin = require_admin_role("admin", "caregiver", "viewer")
require_caregiver = require_admin_role("admin", "caregiver")
require_system_admin = require_admin_role("admin")

def _session_key(elder_id: str, session_id: str = "default", persona_id: str = None) -> str:
    return f"{elder_id}:{session_id or 'default'}:{persona_id or 'profile'}"


def get_decision(elder_id: str, session_id: str = "default", persona_id: str = None) -> Decision:
    key = _session_key(elder_id, session_id, persona_id)
    if key not in decisions:
        decisions[key] = Decision(elder_id, session_id=session_id, persona_id=persona_id)
    return decisions[key]


def _reset_elder_state(elder_id: str, session_id: str = None):
    """Clear cached agents so the next request picks up fresh profile data."""
    clear_agent(elder_id, session_id=session_id)
    prefix = f"{elder_id}:{session_id or ''}"
    for key in list(decisions):
        if key.startswith(prefix):
            decisions.pop(key, None)


def _session_rows() -> list[dict]:
    rows = []
    for key, decision in decisions.items():
        rows.append({
            "key": key,
            "elder_id": decision.elder_id,
            "session_id": decision.session_id,
            "persona_id": decision.persona_id or "profile",
            "chat_count": decision.chat_count,
            "last_seen": decision.last_seen.isoformat(timespec="seconds"),
        })
    rows.sort(key=lambda row: row["last_seen"], reverse=True)
    return rows


# ------------------------------------------------------------------
# Background tasks
# ------------------------------------------------------------------

async def _generate_persona_tone(elder_id: str, persona_id: str):
    """Background task: generate a speaking-style description for a new persona."""
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        if not profile:
            return

        persona = profile.get("personas", {}).get(persona_id)
        if not persona:
            return

        language_map = {
            "mandarin": "全華語，標準國語",
            "taiwanese_mandarin": "台灣國語，帶點本土親切台灣腔",
            "mixed": "國台語夾雜，日常華語但情緒詞和稱呼用台語",
        }
        language_text = language_map.get(persona.get("language", "mandarin"), "全華語")

        llm = LLMService()
        loop = asyncio.get_event_loop()
        tone = await loop.run_in_executor(
            None,
            llm.generate_persona_tone,
            persona.get("relation", ""),
            persona.get("name", ""),
            language_text,
            persona.get("personality", []),
            persona.get("habits", []),
        )

        profile["personas"][persona_id]["tone"] = tone
        memory._save(elder_id, profile)
        print(f"說話風格生成完成：{persona.get('name', '')} → {tone[:30]}...")

    except Exception as e:
        print(f"說話風格生成失敗：{e}")


# ------------------------------------------------------------------
# Static pages
# ------------------------------------------------------------------

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")


@app.get("/admin")
def admin_page(_: dict = Depends(require_admin)):
    return FileResponse("frontend/admin.html")


# ------------------------------------------------------------------
# Session management
# ------------------------------------------------------------------

@app.post("/api/switch-elder")
def switch_elder(req: GreetRequest):
    try:
        _reset_elder_state(req.elder_id, req.session_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Conversation
# ------------------------------------------------------------------

@app.post("/api/greet")
def greet(req: GreetRequest):
    try:
        return get_decision(req.elder_id, req.session_id, req.persona_id).greet()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        decision = get_decision(req.elder_id, req.session_id, req.persona_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, decision.chat, req.message, req.speed_emotion
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Speech I/O
# ------------------------------------------------------------------

@app.post("/api/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    try:
        await ensure_stt_pool()
        audio_bytes = await audio.read()
        stt_instance = await stt_pool_lock.get()
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, stt_instance.transcribe_with_speed, audio_bytes
            )
        finally:
            await stt_pool_lock.put(stt_instance)

        if not result["text"]:
            return {"text": "", "success": False, "speed_emotion": "normal"}
        return {
            "text": result["text"],
            "success": True,
            "speed_emotion": result["speed_emotion"],
            "speech_rate": result["speech_rate"],
            "duration": result["duration"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/me")
def admin_me(user: dict = Depends(require_admin)):
    return user


@app.get("/api/admin/sessions")
def list_sessions(_: dict = Depends(require_caregiver)):
    return {"sessions": _session_rows(), "count": len(decisions)}


@app.post("/api/admin/sessions/clear")
def clear_sessions(req: SessionClearRequest, _: dict = Depends(require_system_admin)):
    if req.elder_id:
        _reset_elder_state(req.elder_id, req.session_id)
    else:
        for key in list(decisions):
            decision = decisions.pop(key)
            clear_agent(decision.elder_id, session_id=decision.session_id)
    return {"success": True, "sessions": _session_rows()}


@app.post("/api/admin/rag/evaluate")
def evaluate_rag(req: RAGEvaluationRequest, _: dict = Depends(require_caregiver)):
    try:
        from backend.tools.rag_evaluation import evaluate_rag_queries
        return evaluate_rag_queries(req.elder_id, req.queries)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/stt/evaluate-transcripts")
def evaluate_stt_transcripts(req: STTEvaluationRequest, _: dict = Depends(require_caregiver)):
    try:
        from backend.tools.stt_corpus_eval import evaluate_transcripts
        return evaluate_transcripts(req.samples)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stt/status")
def get_stt_status():
    try:
        from backend.services.stt_service import get_stt_environment_status

        status = get_stt_environment_status()
        status["pool_initialized"] = bool(stt_pool)
        status["pool_size"] = len(stt_pool)
        status["workers"] = [
            worker.status() if hasattr(worker, "status") else {"available": True}
            for worker in stt_pool
        ]
        status["taiwanese_stt_verified"] = (
            status["transformers_available"] and status["torch_available"] and status["breeze_cache_exists"]
        )
        status["verification_note"] = (
            "Breeze ASR dependency/cache path verified; live microphone accuracy still depends on a real recording sample."
            if status["taiwanese_stt_verified"]
            else "Taiwanese STT dependencies or Breeze ASR cache are incomplete."
        )
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tts")
async def text_to_speech(req: TTSRequest):
    try:
        service = tts
        if req.elder_id:
            memory = VectorMemoryStore()
            profile = memory.get_profile(req.elder_id)
            personas = profile.get("personas", {}) if profile else {}
            active_id = req.persona_id or (profile.get("active_persona", "ai") if profile else "ai")
            active = personas.get(active_id, personas.get("ai", {}))
            voice_path = active.get("voice_path")
            engine = active.get("voice_engine", "xtts")

            service = TTSService(voice="zh-TW-HsiaoChenNeural")
            if voice_path:
                service.set_engine("xtts", voice_path)
            else:
                service.reset_engine()

        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, service.synthesize, req.text, req.emotion)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS 失敗")
        media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
        return Response(content=audio_bytes, media_type=media_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stt/language")
async def set_stt_language(req: LanguageRequest):
    try:
        print(f"收到語言切換請求：{req.language}")
        await ensure_stt_pool()
        for s in stt_pool:
            s.set_language(req.language)
        worker_status = [
            s.status() if hasattr(s, "status") else {"language_mode": req.language}
            for s in stt_pool
        ]
        breeze_loaded = any(s.get("breeze_loaded") for s in worker_status)
        return {
            "success": True,
            "language": req.language,
            "breeze_loaded": breeze_loaded,
            "workers": worker_status,
            "verification_note": (
                "Taiwanese STT route verified with Breeze ASR loaded."
                if req.language == "tai" and breeze_loaded
                else "Language switch route verified; Breeze ASR will fall back if model/runtime is unavailable."
            ),
        }
    except Exception as e:
        print(f"語言切換失敗：{e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Profile
# ------------------------------------------------------------------

@app.get("/api/profile/{elder_id}")
def get_profile(elder_id: str, _: dict = Depends(require_admin)):
    try:
        decision = get_decision(elder_id)
        profile = decision.profile
        if not profile or not profile.get("name"):
            raise HTTPException(status_code=404, detail="找不到長者資料")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/{elder_id}")
def get_history(elder_id: str, _: dict = Depends(require_caregiver)):
    key = next((k for k in decisions if k.startswith(f"{elder_id}:")), None)
    if not key:
        return {"history": []}
    return {"history": decisions[key].get_history()}


@app.get("/api/safety/{elder_id}")
def get_safety(elder_id: str, _: dict = Depends(require_caregiver)):
    try:
        return get_decision(elder_id).get_safety_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent-logs")
def get_agent_logs(_: dict = Depends(require_caregiver)):
    from backend.agents.decision import get_logs
    return {"logs": get_logs()}


@app.post("/api/profile/save")
async def save_profile(req: ElderProfileUpdate, _: dict = Depends(require_caregiver)):
    try:
        data_path = Path("backend/data/elders") / f"{req.elder_id}.json"

        if data_path.exists():
            with open(data_path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        else:
            profile = {
                "elder_id": req.elder_id,
                "recent_events": [],
                "memory_summary": {},
                "elder_biography": {},
                "biography_usage_count": 0,
            }

        profile["name"] = req.name
        profile["gender"] = req.gender
        profile["cognitive_status"] = req.cognitive_status
        profile["persona"] = {
            "former_job": req.former_job,
            "tone_preference": req.tone_preference,
            "hobbies": [h.strip() for h in req.hobbies.split("、") if h.strip()],
        }
        profile["health_notes"] = {
            "sensitivity": [s.strip() for s in req.sensitivity.split("、") if s.strip()],
            "diet": req.diet,
        }

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

        _reset_elder_state(req.elder_id)

        return {"success": True, "message": f"{req.name} 的資料已儲存"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/save-biography")
def save_biography(req: BiographyUpdateRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        profile["elder_biography"] = {
            "content": req.biography,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": req.sources or profile.get("elder_biography", {}).get("sources", []),
            "manually_edited": True,
        }
        profile["biography_usage_count"] = 0
        memory._save(req.elder_id, profile)

        _reset_elder_state(req.elder_id)
        return {"success": True, "message": "生平資料已儲存"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Personas
# ------------------------------------------------------------------

@app.get("/api/profile/{elder_id}/personas")
def get_personas(elder_id: str, _: dict = Depends(require_admin)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        return {
            "personas": profile.get("personas", {}),
            "active_persona": profile.get("active_persona", "ai"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/persona/add")
async def add_persona(req: PersonaAddRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        if "personas" not in profile:
            profile["personas"] = {}

        existing_count = len([k for k in profile["personas"] if k != "ai"])
        persona_id = f"persona_{existing_count + 1}"

        profile["personas"][persona_id] = {
            "name": req.name,
            "relation": req.relation,
            "voice_engine": req.voice_engine,
            "voice_path": req.voice_path,
            "honorific": req.honorific,
            "language": req.language,
            "personality": req.personality,
            "habits": req.habits,
            "tone": "",
            "is_deceased": req.is_deceased,
            "shared_memories": req.shared_memories,
            "current_status": req.current_status,
            "forbidden_topics": req.forbidden_topics,
        }
        memory._save(req.elder_id, profile)

        asyncio.create_task(_generate_persona_tone(req.elder_id, persona_id))

        _reset_elder_state(req.elder_id)
        return {"success": True, "message": f"已新增：{req.name}", "persona_id": persona_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/persona/delete")
def delete_persona(req: PersonaDeleteRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        if req.persona_id == "ai":
            raise HTTPException(status_code=400, detail="不能刪除 AI 助理")

        personas = profile.get("personas", {})
        personas.pop(req.persona_id, None)
        profile["personas"] = personas

        if profile.get("active_persona") == req.persona_id:
            profile["active_persona"] = "ai"

        memory._save(req.elder_id, profile)
        _reset_elder_state(req.elder_id)
        return {"success": True, "message": "已刪除人格"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/persona/switch")
def switch_persona(req: PersonaSwitchRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        personas = profile.get("personas", {})
        if req.persona_id not in personas:
            raise HTTPException(status_code=404, detail="找不到此人格")

        profile["active_persona"] = req.persona_id
        memory._save(req.elder_id, profile)
        _reset_elder_state(req.elder_id)
        return {
            "success": True,
            "message": f"已切換到：{personas[req.persona_id]['name']}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/persona/upload-voice")
async def upload_voice(
    elder_id: str = Form(...),
    persona_id: str = Form(...),
    voice: UploadFile = File(...),
    _: dict = Depends(require_caregiver),
):
    try:
        voices_dir = Path(f"backend/data/elders/{elder_id}_voices")
        voices_dir.mkdir(exist_ok=True)

        voice_path = voices_dir / f"{persona_id}.wav"
        with open(voice_path, "wb") as f:
            shutil.copyfileobj(voice.file, f)

        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        if profile and "personas" in profile and persona_id in profile["personas"]:
            profile["personas"][persona_id]["voice_path"] = str(voice_path)
            profile["personas"][persona_id]["voice_engine"] = "xtts"
            memory._save(elder_id, profile)

        _reset_elder_state(elder_id)
        return {"success": True, "message": "語音樣本已上傳", "path": str(voice_path)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/background-candidates")
def background_candidates(req: BackgroundCandidateRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            return {"success": False, "message": "找不到長者資料"}

        search = SearchService()
        result = search.search_background_candidates(profile, req.extra_keywords)
        return {
            "success": True,
            "queries": result.get("queries", []),
            "candidates": result.get("candidates", []),
            "message": result.get("message", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/biography-draft")
def biography_draft(req: BiographyDraftRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            return {"success": False, "message": "找不到長者資料"}

        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})
        sources = req.selected_sources or []
        raw_summary = "\n".join(
            f"- {s.get('title', '')}: {s.get('summary', '')}"
            for s in sources
            if s.get("summary") or s.get("title")
        )

        search = SearchService()
        biography = search.generate_biography(
            name=profile.get("name", ""),
            gender=profile.get("gender", "male"),
            job=persona.get("former_job", "未知"),
            hobbies=persona.get("hobbies", []),
            personas=profile.get("personas", {}),
            health=health,
            raw_summary=raw_summary,
        )

        if not biography or len(biography) < 20:
            return {"success": False, "message": "生平草稿生成失敗"}

        return {
            "success": True,
            "message": "已產生生平草稿，請確認後再儲存。",
            "biography": biography,
            "sources": [
                {"title": s.get("title", ""), "url": s.get("url", "")}
                for s in sources
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/persona/upload-avatar")
async def upload_avatar(
    elder_id: str = Form(...),
    persona_id: str = Form(...),
    avatar: UploadFile = File(...),
    _: dict = Depends(require_caregiver),
):
    try:
        suffix = Path(avatar.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=400, detail="只支援 png、jpg、jpeg、webp")

        avatars_dir = Path("frontend/avatars/personas")
        avatars_dir.mkdir(parents=True, exist_ok=True)
        avatar_filename = f"{elder_id}_{persona_id}{suffix}"
        avatar_path = avatars_dir / avatar_filename
        with open(avatar_path, "wb") as f:
            shutil.copyfileobj(avatar.file, f)

        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        if not profile or "personas" not in profile or persona_id not in profile["personas"]:
            raise HTTPException(status_code=404, detail="找不到此人格")

        profile["personas"][persona_id]["avatar_path"] = f"personas/{avatar_filename}"
        memory._save(elder_id, profile)

        _reset_elder_state(elder_id)
        return {
            "success": True,
            "message": "陪伴者照片已上傳",
            "avatar_path": f"personas/{avatar_filename}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Family notes
# ------------------------------------------------------------------

@app.post("/api/profile/family-note/add")
def add_family_note(req: FamilyNoteRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")
        if "family_notes" not in profile:
            profile["family_notes"] = []
        profile["family_notes"].append({
            "note": req.note,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "added_by": "照護人員",
        })
        memory._save(req.elder_id, profile)
        return {"success": True, "family_notes": profile["family_notes"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/family-note/delete")
def delete_family_note(req: FamilyNoteDeleteRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")
        notes = profile.get("family_notes", [])
        if 0 <= req.index < len(notes):
            notes.pop(req.index)
            profile["family_notes"] = notes
            memory._save(req.elder_id, profile)
        return {"success": True, "family_notes": profile["family_notes"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
