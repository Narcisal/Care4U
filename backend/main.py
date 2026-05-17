import json
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Optional
from backend.agents.decision import Decision, clear_agent
from backend.services.stt_service import STTService
from backend.services.tts_service import TTSService
from fastapi import Form

app = FastAPI(title="AI Care U")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

stt = STTService(model_size="medium", device="cpu")
tts = TTSService(voice="zh-TW-HsiaoChenNeural")
decisions: dict[str, Decision] = {}

def get_decision(elder_id: str) -> Decision:
    if elder_id not in decisions:
        decisions[elder_id] = Decision(elder_id)
    return decisions[elder_id]

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
    family: str

class ElderSearchRequest(BaseModel):
    elder_id: str
    name: str
    keywords: list

class BiographyUpdateRequest(BaseModel):
    elder_id: str
    biography: str

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

@app.get("/admin")
def admin_page():
    return FileResponse("frontend/admin.html")

@app.post("/api/switch-elder")
def switch_elder(req: GreetRequest):
    try:
        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/greet")
def greet(req: GreetRequest):
    try:
        decision = get_decision(req.elder_id)
        return decision.greet()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        decision = get_decision(req.elder_id)
        return decision.chat(req.message, req.speed_emotion)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        result = stt.transcribe_with_speed(audio_bytes)
        if not result["text"]:
            return {"text": "", "success": False, "speed_emotion": "normal"}
        return {
            "text": result["text"],
            "success": True,
            "speed_emotion": result["speed_emotion"],
            "speech_rate": result["speech_rate"],
            "duration": result["duration"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tts")
def text_to_speech(req: TTSRequest):
    try:
        audio_bytes = tts.synthesize(req.text, req.emotion)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS 失敗")
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profile/{elder_id}")
def get_profile(elder_id: str):
    try:
        decision = get_decision(elder_id)
        if not decision.profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")
        return decision.profile
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history/{elder_id}")
def get_history(elder_id: str):
    if elder_id not in decisions:
        return {"history": []}
    return {"history": decisions[elder_id].get_history()}

@app.get("/api/safety/{elder_id}")
def get_safety(elder_id: str):
    try:
        decision = get_decision(elder_id)
        return decision.get_safety_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agent-logs")
def get_agent_logs():
    from backend.agents.decision import get_logs
    return {"logs": get_logs()}

@app.post("/api/profile/save")
def save_profile(req: ElderProfileUpdate):
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
                "biography_usage_count": 0
            }

        profile["name"] = req.name
        profile["gender"] = req.gender
        profile["persona"] = {
            "former_job": req.former_job,
            "tone_preference": req.tone_preference,
            "hobbies": [h.strip() for h in req.hobbies.split("、") if h.strip()],
            "family": {}
        }
        profile["health_notes"] = {
            "sensitivity": [s.strip() for s in req.sensitivity.split("、") if s.strip()],
            "diet": req.diet
        }

        try:
            family = json.loads(req.family)
        except Exception:
            family = {}
        profile["persona"]["family"] = family

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)

        return {"success": True, "message": f"{req.name} 的資料已儲存"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/search-background")
def search_elder_background(req: ElderSearchRequest):
    try:
        from backend.tools.search_service import SearchService
        from backend.memory.vector_store import VectorMemoryStore
        from backend.services.embedding_service import EmbeddingService

        search = SearchService()
        result = search.search_elder_background(req.name, req.keywords)

        if not result["found"]:
            return {"success": False, "message": "找不到相關公開資料"}

        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            return {"success": False, "message": "找不到長者資料"}

        biography = search.generate_biography(
            result["summary"], req.name, profile
        )

        if not biography or biography == "無相關公開資料":
            return {"success": False, "message": "找不到相關公開資料"}

        profile["elder_biography"] = {
            "content": biography,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": result["sources"],
            "manually_edited": False
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
            "source": "web_search"
        }
        memory.add_event(req.elder_id, event)

        try:
            emb = embedding_service.embed(biography)
            if emb:
                cursor = memory._get_cursor()
                if cursor:
                    cursor.execute("""
                        SELECT id FROM elder_memories
                        WHERE elder_id = %s
                        ORDER BY created_at DESC LIMIT 1
                    """, (req.elder_id,))
                    row = cursor.fetchone()
                    if row:
                        memory.update_embedding(row['id'], emb)
        except Exception as e:
            print(f"向量生成失敗：{e}")

        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)

        return {
            "success": True,
            "message": f"已整理 {req.name} 的生平資料",
            "biography": biography,
            "sources": result["sources"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/save-biography")
def save_biography(req: BiographyUpdateRequest):
    try:
        from backend.memory.vector_store import VectorMemoryStore

        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        profile["elder_biography"] = {
            "content": req.biography,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": profile.get("elder_biography", {}).get("sources", []),
            "manually_edited": True
        }
        profile["biography_usage_count"] = 0
        memory._save(req.elder_id, profile)

        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)

        return {"success": True, "message": "生平資料已儲存"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
class PersonaAddRequest(BaseModel):
    elder_id: str
    persona_id: str
    name: str
    relation: str
    honorific: str
    tone: str
    voice_engine: str = "edge"
    voice_path: str = None

class PersonaDeleteRequest(BaseModel):
    elder_id: str
    persona_id: str

class PersonaSwitchRequest(BaseModel):
    elder_id: str
    persona_id: str

@app.get("/api/profile/{elder_id}/personas")
def get_personas(elder_id: str):
    try:
        from backend.memory.vector_store import VectorMemoryStore
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        return {
            "personas": profile.get("personas", {}),
            "active_persona": profile.get("active_persona", "ai")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/persona/add")
def add_persona(req: PersonaAddRequest):
    try:
        from backend.memory.vector_store import VectorMemoryStore
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        if "personas" not in profile:
            profile["personas"] = {}

        profile["personas"][req.persona_id] = {
            "name": req.name,
            "relation": req.relation,
            "voice_engine": req.voice_engine,
            "voice_path": req.voice_path,
            "honorific": req.honorific,
            "tone": req.tone
        }
        memory._save(req.elder_id, profile)
        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)
        return {"success": True, "message": f"已新增人格：{req.name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/persona/delete")
def delete_persona(req: PersonaDeleteRequest):
    try:
        from backend.memory.vector_store import VectorMemoryStore
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        if req.persona_id == "ai":
            raise HTTPException(status_code=400, detail="不能刪除 AI 助理")

        personas = profile.get("personas", {})
        if req.persona_id in personas:
            del personas[req.persona_id]
            profile["personas"] = personas

        if profile.get("active_persona") == req.persona_id:
            profile["active_persona"] = "ai"

        memory._save(req.elder_id, profile)
        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)
        return {"success": True, "message": "已刪除人格"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/persona/switch")
def switch_persona(req: PersonaSwitchRequest):
    try:
        from backend.memory.vector_store import VectorMemoryStore
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        personas = profile.get("personas", {})
        if req.persona_id not in personas:
            raise HTTPException(status_code=404, detail="找不到此人格")

        profile["active_persona"] = req.persona_id
        memory._save(req.elder_id, profile)
        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)
        return {
            "success": True,
            "message": f"已切換到：{personas[req.persona_id]['name']}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/persona/upload-voice")
async def upload_voice(
    elder_id: str = Form(...),
    persona_id: str = Form(...),
    voice: UploadFile = File(...)
):
    try:
        import shutil
        voices_dir = Path(f"backend/data/elders/{elder_id}_voices")
        voices_dir.mkdir(exist_ok=True)

        voice_path = voices_dir / f"{persona_id}.wav"
        with open(voice_path, "wb") as f:
            shutil.copyfileobj(voice.file, f)

        from backend.memory.vector_store import VectorMemoryStore
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        if profile and "personas" in profile and persona_id in profile["personas"]:
            profile["personas"][persona_id]["voice_path"] = str(voice_path)
            profile["personas"][persona_id]["voice_engine"] = "breezyvoice"
            memory._save(elder_id, profile)

        clear_agent(elder_id)
        decisions.pop(elder_id, None)
        return {"success": True, "message": "語音樣本已上傳", "path": str(voice_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))