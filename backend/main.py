import json
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

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

@app.get("/admin")
def admin_page():
    return FileResponse("frontend/admin.html")

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
            profile = {"elder_id": req.elder_id, "recent_events": []}

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
            for item in req.family.split("、"):
                if "：" in item:
                    role, name = item.split("：", 1)
                    family[role.strip()] = name.strip()
        profile["persona"]["family"] = family

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)

        return {"success": True, "message": f"{req.name} 的資料已儲存"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/switch-elder")
def switch_elder(req: GreetRequest):
    try:
        # 清除舊的 agent
        clear_agent(req.elder_id)
        decisions.pop(req.elder_id, None)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/profile/search-background")
def search_elder_background(req: ElderSearchRequest):
    try:
        from backend.tools.search_service import SearchService
        from backend.memory.vector_store import VectorMemoryStore
        from backend.services.embedding_service import EmbeddingService
        from backend.services.llm_service import LLMService

        search = SearchService()
        result = search.search_elder_background(req.name, req.keywords)

        if not result["found"]:
            return {"success": False, "message": "找不到相關公開資料"}

        llm = LLMService()
        filtered = search.filter_relevant_info(result["summary"], req.name, llm)

        if filtered == "無相關公開資料" or not filtered:
            return {"success": False, "message": "找不到相關公開資料"}

        memory = VectorMemoryStore()
        embedding_service = EmbeddingService()

        event = {
            "event": f"背景資料：{filtered}",
            "sentiment": "neutral",
            "emotion_score": 0.0,
            "importance": 0.9,
            "memory_type": "long",
            "topic_tags": ["背景資料", "公開資訊"],
            "reason": f"來源：{', '.join([s['title'] for s in result['sources'][:2]])}",
            "source": "web_search"
        }

        memory.add_event(req.elder_id, event)

        try:
            emb = embedding_service.embed(filtered)
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

        return {
            "success": True,
            "message": f"找到 {req.name} 的背景資料",
            "summary": filtered,
            "sources": result["sources"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))