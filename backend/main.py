from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
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

# 初始化服務
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

# ====== 路由 ======

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

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
        return {
            "message": response,
            "elder_id": req.elder_id,
            "history_length": len(agent.get_history())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """接收音訊檔案，回傳辨識文字"""
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
    """接收文字，回傳音訊"""
    try:
        audio_bytes = tts.synthesize(req.text)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS 失敗")
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat_with_tts")
def chat_with_tts(req: ChatRequest):
    """對話並回傳音訊"""
    try:
        if req.elder_id not in agents:
            agents[req.elder_id] = MagicAI(req.elder_id)
        agent = agents[req.elder_id]
        
        # 取得文字回應
        response_text = agent.chat(req.message)
        
        # 轉成語音
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