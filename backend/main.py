import asyncio
import json
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agents.decision import Decision, clear_agent
from backend.services.stt_service import STTService
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

# ------------------------------------------------------------------
# STT worker pool
# ------------------------------------------------------------------

STT_POOL_SIZE = 3
try:
    stt_pool = [STTService(model_size="medium", device="cuda") for _ in range(STT_POOL_SIZE)]
except Exception as e:
    traceback.print_exc()
    print(f"STTService CUDA 初始化失敗，退回 CPU：{e}")
    stt_pool = [STTService(model_size="medium", device="cpu") for _ in range(STT_POOL_SIZE)]

stt_pool_lock: asyncio.Queue = asyncio.Queue()
tts = TTSService(voice="zh-TW-HsiaoChenNeural")
decisions: dict[str, Decision] = {}


@app.on_event("startup")
async def startup_event():
    for s in stt_pool:
        await stt_pool_lock.put(s)
    print(f"STT worker pool 初始化完成，共 {STT_POOL_SIZE} 個實例")


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    elder_id: str
    message: str
    speed_emotion: str = "normal"

class GreetRequest(BaseModel):
    elder_id: str

class TTSRequest(BaseModel):
    text: str
    emotion: str = "normal"

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

class ElderSearchRequest(BaseModel):
    elder_id: str
    name: str
    keywords: list

class BiographyUpdateRequest(BaseModel):
    elder_id: str
    biography: str

class PersonaAddRequest(BaseModel):
    elder_id: str
    name: str
    relation: str
    honorific: str
    language: str = "mandarin"
    personality: list = []
    habits: list = []
    voice_engine: str = "edge"
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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def get_decision(elder_id: str) -> Decision:
    if elder_id not in decisions:
        decisions[elder_id] = Decision(elder_id)
    return decisions[elder_id]


def _reset_elder_state(elder_id: str):
    """Clear cached agents so the next request picks up fresh profile data."""
    clear_agent(elder_id)
    decisions.pop(elder_id, None)


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


async def _auto_search_biography(elder_id: str, name: str):
    """Background task: search the web and generate a biography on first profile save."""
    try:
        print(f"自動搜尋生平資料：{name}")
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        if not profile:
            return

        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})
        search = SearchService()
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None, search.search_elder_background, name, [name]
        )
        raw_summary = result.get("summary", "") if result.get("found") else ""

        biography = await loop.run_in_executor(
            None,
            search.generate_biography,
            name,
            profile.get("gender", "male"),
            persona.get("former_job", "未知"),
            persona.get("hobbies", []),
            profile.get("personas", {}),
            health,
            raw_summary,
        )

        if biography and len(biography) > 20:
            profile["elder_biography"] = {
                "content": biography,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sources": ["web_search"] if raw_summary else ["basic_profile"],
                "manually_edited": False,
            }
            memory._save(elder_id, profile)
            print(f"自動生平完成：{name}")

    except Exception as e:
        print(f"自動生平搜尋失敗：{e}")


# ------------------------------------------------------------------
# Static pages
# ------------------------------------------------------------------

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")


@app.get("/admin")
def admin_page():
    return FileResponse("frontend/admin.html")


# ------------------------------------------------------------------
# Session management
# ------------------------------------------------------------------

@app.post("/api/switch-elder")
def switch_elder(req: GreetRequest):
    try:
        _reset_elder_state(req.elder_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Conversation
# ------------------------------------------------------------------

@app.post("/api/greet")
def greet(req: GreetRequest):
    try:
        return get_decision(req.elder_id).greet()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        decision = get_decision(req.elder_id)
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


@app.post("/api/tts")
async def text_to_speech(req: TTSRequest):
    try:
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, tts.synthesize, req.text, req.emotion)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS 失敗")
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stt/language")
def set_stt_language(req: LanguageRequest):
    try:
        print(f"收到語言切換請求：{req.language}")
        for s in stt_pool:
            s.set_language(req.language)
        return {"success": True, "language": req.language}
    except Exception as e:
        print(f"語言切換失敗：{e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Profile
# ------------------------------------------------------------------

@app.get("/api/profile/{elder_id}")
def get_profile(elder_id: str):
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
def get_history(elder_id: str):
    if elder_id not in decisions:
        return {"history": []}
    return {"history": decisions[elder_id].get_history()}


@app.get("/api/safety/{elder_id}")
def get_safety(elder_id: str):
    try:
        return get_decision(elder_id).get_safety_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent-logs")
def get_agent_logs():
    from backend.agents.decision import get_logs
    return {"logs": get_logs()}


@app.post("/api/profile/save")
async def save_profile(req: ElderProfileUpdate):
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
        asyncio.create_task(_auto_search_biography(req.elder_id, req.name))

        return {"success": True, "message": f"{req.name} 的資料已儲存"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/search-background")
def search_elder_background(req: ElderSearchRequest):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            return {"success": False, "message": "找不到長者資料"}

        persona = profile.get("persona", {})
        health = profile.get("health_notes", {})
        search = SearchService()

        result = search.search_elder_background(req.name, req.keywords)
        raw_summary = result.get("summary", "") if result.get("found") else ""

        biography = search.generate_biography(
            name=req.name,
            gender=profile.get("gender", "male"),
            job=persona.get("former_job", "未知"),
            hobbies=persona.get("hobbies", []),
            personas=profile.get("personas", {}),
            health=health,
            raw_summary=raw_summary,
        )

        if not biography or len(biography) < 20:
            return {"success": False, "message": "生平生成失敗"}

        profile["elder_biography"] = {
            "content": biography,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": result["sources"],
            "manually_edited": False,
        }
        profile["biography_usage_count"] = 0
        memory._save(req.elder_id, profile)

        embedding_service = EmbeddingService()
        event = {
            "event": f"生平資料：{biography[:100]}",
            "sentiment": "neutral",
            "emotion_score": 0.0,
            "importance": 0.95,
            "memory_type": "long",
            "topic_tags": ["生平資料", "背景資訊"],
            "reason": "網路搜尋整理的生平文章",
            "source": "web_search",
        }
        memory.add_event(req.elder_id, event)

        try:
            emb = embedding_service.embed(biography)
            if emb:
                cursor = memory._get_cursor()
                if cursor:
                    cursor.execute(
                        "SELECT id FROM elder_memories WHERE elder_id = %s ORDER BY created_at DESC LIMIT 1",
                        (req.elder_id,),
                    )
                    row = cursor.fetchone()
                    if row:
                        memory.update_embedding(row["id"], emb)
        except Exception as e:
            print(f"向量生成失敗：{e}")

        _reset_elder_state(req.elder_id)

        return {
            "success": True,
            "message": f"已整理 {req.name} 的生平資料",
            "biography": biography,
            "sources": result["sources"],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/save-biography")
def save_biography(req: BiographyUpdateRequest):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        profile["elder_biography"] = {
            "content": req.biography,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": profile.get("elder_biography", {}).get("sources", []),
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
def get_personas(elder_id: str):
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
async def add_persona(req: PersonaAddRequest):
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
def delete_persona(req: PersonaDeleteRequest):
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
def switch_persona(req: PersonaSwitchRequest):
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
            profile["personas"][persona_id]["voice_engine"] = "breezyvoice"
            memory._save(elder_id, profile)

        _reset_elder_state(elder_id)
        return {"success": True, "message": "語音樣本已上傳", "path": str(voice_path)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Family notes
# ------------------------------------------------------------------

@app.post("/api/profile/family-note/add")
def add_family_note(req: FamilyNoteRequest):
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
def delete_family_note(req: FamilyNoteDeleteRequest):
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
