import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Optional
from backend.agents.magic_ai import MagicAI
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
agents: dict[str, MagicAI] = {}

# ====== 資料格式 ======
class ChatRequest(BaseModel):
    elder_id: str
    message: str

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

# ====== 路由 ======

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

@app.get("/admin")
def admin_page():
    return FileResponse("frontend/admin.html")

@app.post("/api/greet")
def greet(req: GreetRequest):
    try:
        if req.elder_id not in agents:
            agents[req.elder_id] = MagicAI(req.elder_id)
        agent = agents[req.elder_id]
        greeting = agent.greet()
        return {"message": greeting, "elder_id": req.elder_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        if req.elder_id not in agents:
            agents[req.elder_id] = MagicAI(req.elder_id)
        agent = agents[req.elder_id]
        response = agent.chat(req.message)

        negative = ["痛", "不舒服", "難過", "孤單", "想哭", "累", "憂鬱"]
        positive = ["開心", "高興", "好棒", "謝謝", "喜歡"]
        urgent = ["跌倒", "頭暈", "胸痛", "喘不過氣"]

        if any(kw in req.message for kw in urgent):
            emotion = "urgent"
        elif any(kw in req.message for kw in negative):
            emotion = "comfort"
        elif any(kw in req.message for kw in positive):
            emotion = "happy"
        else:
            emotion = "normal"

        return {
            "message": response,
            "emotion": emotion,
            "elder_id": req.elder_id,
            "history_length": len(agent.get_history())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        text = stt.transcribe(audio_bytes)
        if not text:
            return {"text": "", "success": False}
        return {"text": text, "success": True}
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

@app.post("/api/chat_with_tts")
def chat_with_tts(req: ChatRequest):
    try:
        if req.elder_id not in agents:
            agents[req.elder_id] = MagicAI(req.elder_id)
        agent = agents[req.elder_id]
        response_text = agent.chat(req.message)
        audio_bytes = tts.synthesize(response_text)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"X-Response-Text": response_text.encode('utf-8').hex()}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profile/{elder_id}")
def get_profile(elder_id: str):
    try:
        if elder_id not in agents:
            agents[elder_id] = MagicAI(elder_id)
        profile = agents[elder_id].profile
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history/{elder_id}")
def get_history(elder_id: str):
    if elder_id not in agents:
        return {"history": []}
    return {"history": agents[elder_id].get_history()}

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
                "recent_events": []
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

        family = {}
        for item in req.family.split("、"):
            if "：" in item:
                role, name = item.split("：", 1)
                family[role.strip()] = name.strip()
        profile["persona"]["family"] = family

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

        if req.elder_id in agents:
            del agents[req.elder_id]

        return {"success": True, "message": f"{req.name} 的資料已儲存"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))