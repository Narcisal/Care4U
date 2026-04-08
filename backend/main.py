from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.agents.magic_ai import MagicAI
import os

app = FastAPI(title="AI Care U")

# 允許前端跨域請求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載前端靜態檔案
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# 儲存每個長者的 Agent 實例
agents: dict[str, MagicAI] = {}

# ====== 資料格式定義 ======
class ChatRequest(BaseModel):
    elder_id: str
    message: str

class GreetRequest(BaseModel):
    elder_id: str

# ====== API 路由 ======

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

@app.post("/api/greet")
def greet(req: GreetRequest):
    """系統啟動，取得問候語"""
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
    """處理使用者訊息"""
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

@app.get("/api/profile/{elder_id}")
def get_profile(elder_id: str):
    """取得長者資料"""
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
    """取得對話歷史"""
    if elder_id not in agents:
        return {"history": []}
    return {"history": agents[elder_id].get_history()}