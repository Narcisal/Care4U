import asyncio
import json
import os
import shutil
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import secrets
import threading
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Path as ApiPath, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, field_validator

load_dotenv(override=True)

from backend.agents.decision import Decision, clear_agent, flush_agent_conversations
from backend.services.tts_service import TTSService
from backend.memory.vector_store import VectorMemoryStore, close_db_pool
from backend.services.embedding_service import EmbeddingService
from backend.services.llm_service import LLMService
from backend.tools.search_service import SearchService
from backend.elder_sessions import (
    ElderIdentity,
    FailRecord,
    InvalidPinError,
    LoginRateLimitedError,
    issue_pin,
    login_with_pin,
    revoke_elder,
    validate_token,
)
from backend.utils.validators import (
    validate_elder_id,
    validate_persona_id,
    validate_session_id,
)

CARE4U_DEMO_MODE = os.getenv("CARE4U_DEMO_MODE", "true").lower() == "true"

# ── 長者 ID 管理：優先掃目錄，.env 可做 override ─────────────────────
_ELDERS_DATA_DIR = Path(__file__).parent / "data" / "elders"

# 百家姓拼音首字母對照（常見台灣姓氏）
_SURNAME_INITIAL: dict[str, str] = {
    "王": "W", "吳": "W", "魏": "W", "翁": "W", "溫": "W",
    "陳": "C", "蔡": "C", "曹": "C", "蔣": "C", "崔": "C",
    "林": "L", "李": "L", "劉": "L", "廖": "L", "賴": "L", "呂": "L", "羅": "L",
    "張": "Z", "鄭": "Z", "趙": "Z", "周": "Z", "朱": "Z", "莊": "Z", "曾": "Z",
    "黃": "H", "洪": "H", "何": "H", "韓": "H",
    "楊": "Y", "葉": "Y", "游": "Y", "余": "Y",
    "許": "X", "謝": "X", "蕭": "X", "徐": "X", "薛": "X",
    "郭": "G", "高": "G", "龔": "G",
    "江": "J", "蔣": "J",
    "邱": "Q",
    "蘇": "S", "宋": "S", "沈": "S",
    "馬": "M", "孟": "M",
    "彭": "P",
    "唐": "T",
    "范": "F", "方": "F", "傅": "F",
    "鍾": "Z", "鄒": "Z",
    "盧": "L", "柯": "K",
}

def _discover_elder_ids() -> set[str]:
    """掃描 data/elders/*.json 取得有效長者 ID；.env 的 ALLOWED_ELDER_IDS 合併進來。"""
    ids: set[str] = set()
    if _ELDERS_DATA_DIR.exists():
        for p in _ELDERS_DATA_DIR.glob("*.json"):
            stem = p.stem
            if "_conv" not in stem:
                try:
                    ids.add(validate_elder_id(stem))
                except ValueError:
                    pass
    # .env override（向下相容）
    env_val = os.getenv("ALLOWED_ELDER_IDS", "").strip()
    if env_val:
        for v in env_val.split(","):
            v = v.strip()
            if v:
                try:
                    ids.add(validate_elder_id(v))
                except ValueError:
                    pass
    return ids

def generate_elder_id(surname: str) -> str:
    """根據姓氏產生下一個可用的長者 ID（如 W002）。"""
    initial = _SURNAME_INITIAL.get(surname[0] if surname else "", "E")
    existing = _discover_elder_ids()
    same_prefix = [
        int(eid[1:]) for eid in existing
        if len(eid) == 4 and eid[0] == initial and eid[1:].isdigit()
    ]
    next_num = (max(same_prefix) + 1) if same_prefix else 1
    return f"{initial}{next_num:03d}"

# 模組層級可變 set（可在 runtime 新增）
ALLOWED_ELDER_IDS: set[str] = _discover_elder_ids()
if not ALLOWED_ELDER_IDS:
    raise RuntimeError("找不到任何長者資料，請確認 data/elders/ 目錄或 ALLOWED_ELDER_IDS 設定")


@asynccontextmanager
async def lifespan(_: FastAPI):
    print(
        f"STT worker pool 延遲初始化：size={STT_POOL_SIZE}, "
        f"model={STT_MODEL_SIZE}, device={STT_DEVICE}"
    )
    _db_enabled_val = os.getenv("DB_ENABLED", "false")
    print(f"[startup] DB_ENABLED={_db_enabled_val!r}  CARE4U_DEMO_MODE={os.getenv('CARE4U_DEMO_MODE','?')!r}")
    if _db_enabled_val.lower() == "true":
        from backend.memory.vector_store import _init_pool
        _init_pool()
    yield
    flush_agent_conversations()
    close_db_pool()


app = FastAPI(title="AI Care U", lifespan=lifespan)

_cors_raw = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = [
    origin.strip()
    for origin in _cors_raw.split(",")
    if origin.strip()
]
if not ALLOWED_ORIGINS and CARE4U_DEMO_MODE:
    ALLOWED_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")
admin_security = HTTPBasic(auto_error=False)
elder_security = HTTPBearer(auto_error=False)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_USERS = os.getenv("ADMIN_USERS", "")
DEMO_AUTH_ROLE = os.getenv("CARE4U_DEMO_AUTH_ROLE", "admin")
ADMIN_AUTH_MAX_FAILURES = 5
ADMIN_AUTH_LOCK_SECONDS = 60
admin_auth_fail_counts: dict[str, FailRecord] = {}
admin_auth_fail_lock = threading.Lock()

# ------------------------------------------------------------------
# STT worker pool
# ------------------------------------------------------------------

STT_POOL_SIZE = int(os.getenv("STT_POOL_SIZE", "1"))
STT_MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "medium")
STT_DEVICE = os.getenv("STT_DEVICE", "cuda")
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "100"))
stt_pool: list[object] = []
stt_pool_lock: asyncio.Queue = asyncio.Queue()
stt_init_lock = asyncio.Lock()
tts = TTSService(voice="zh-TW-HsiaoChenNeural")
decisions: dict[str, Decision] = {}
chat_background_results: dict[str, dict] = {}
chat_background_results_lock = threading.Lock()
BACKGROUND_RESULTS_MAX = 200
BACKGROUND_RESULTS_TTL_SECONDS = 300


def _background_all_done(result: dict) -> bool:
    return (
        result.get("image_status") in {"complete", "failed"}
        and result.get("health_status") in {"complete", "failed"}
    )


def _update_background_result(task_id: str, values: dict):
    with chat_background_results_lock:
        result = chat_background_results.get(task_id)
        if result is None:
            return
        result.update(values)
        if _background_all_done(result):
            result.setdefault("_completed_at", time.monotonic())


def _reserve_background_result(owner_token: str) -> str | None:
    now = time.monotonic()
    with chat_background_results_lock:
        expired = [
            task_id
            for task_id, result in chat_background_results.items()
            if _background_all_done(result)
            and now - result.get("_completed_at", now)
            >= BACKGROUND_RESULTS_TTL_SECONDS
        ]
        for task_id in expired:
            chat_background_results.pop(task_id, None)

        while len(chat_background_results) >= BACKGROUND_RESULTS_MAX:
            terminal = [
                (result.get("_created_at", now), task_id)
                for task_id, result in chat_background_results.items()
                if _background_all_done(result)
            ]
            if not terminal:
                return None
            _, oldest_task_id = min(terminal)
            chat_background_results.pop(oldest_task_id, None)

        task_id = secrets.token_urlsafe(16)
        chat_background_results[task_id] = {
            "image_status": "pending",
            "image": None,
            "image_caption": None,
            "health_status": "pending",
            "health_info": None,
            "_owner_token": owner_token,
            "_created_at": now,
        }
        return task_id


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

class ValidatedRequest(BaseModel):
    @field_validator("elder_id", check_fields=False)
    @classmethod
    def validate_elder_identifier(cls, value: Optional[str]) -> Optional[str]:
        return validate_elder_id(value) if value is not None else None

    @field_validator("persona_id", check_fields=False)
    @classmethod
    def validate_persona_identifier(cls, value: Optional[str]) -> Optional[str]:
        return validate_persona_id(value) if value is not None else None

    @field_validator("session_id", check_fields=False)
    @classmethod
    def validate_session_identifier(cls, value: Optional[str]) -> Optional[str]:
        return validate_session_id(value) if value is not None else None


class ChatRequest(ValidatedRequest):
    elder_id: str
    message: str
    speed_emotion: str = "normal"
    session_id: str = "default"
    persona_id: Optional[str] = None

class GreetRequest(ValidatedRequest):
    elder_id: str
    session_id: str = "default"
    persona_id: Optional[str] = None

class TTSRequest(ValidatedRequest):
    text: str
    emotion: str = "normal"
    elder_id: Optional[str] = None
    persona_id: Optional[str] = None

class ElderProfileUpdate(ValidatedRequest):
    elder_id: str
    name: str
    gender: str
    former_job: str
    tone_preference: str
    hobbies: str
    sensitivity: str
    diet: str
    cognitive_status: str = "normal"
    active_persona: Optional[str] = None

    @field_validator("active_persona")
    @classmethod
    def validate_active_persona(cls, value: Optional[str]) -> Optional[str]:
        return validate_persona_id(value) if value else value

class BackgroundCandidateRequest(ValidatedRequest):
    elder_id: str
    extra_keywords: list = []

class BiographyDraftRequest(ValidatedRequest):
    elder_id: str
    selected_sources: list = []

class BiographyUpdateRequest(ValidatedRequest):
    elder_id: str
    biography: str
    sources: Optional[list] = None

class CreateElderRequest(BaseModel):
    """新增長者請求。elder_id 若留空則自動產生。"""
    name: str
    gender: str = "male"
    birth_year: Optional[int] = None
    hometown: str = ""
    cognitive_status: str = "normal"
    job: str = ""
    hobbies: list = []
    family_members: list = []   # [{"relation": "兒子", "name": "志明"}, ...]
    hints: str = ""             # admin 手填的關鍵人生事件
    biography: str = ""         # 最終確認的傳記（可空，之後再填）
    elder_id: str = ""          # 留空則自動產生

class BiographyPreviewRequest(BaseModel):
    """新長者傳記預覽請求（不需要已存在的 elder_id）。"""
    name: str
    gender: str = "male"
    birth_year: Optional[int] = None
    hometown: str = ""
    job: str = ""
    hobbies: list = []
    family_members: list = []
    hints: str = ""

class PersonaAddRequest(ValidatedRequest):
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

class PersonaDeleteRequest(ValidatedRequest):
    elder_id: str
    persona_id: str

class PersonaSwitchRequest(ValidatedRequest):
    elder_id: str
    persona_id: str

class LanguageRequest(ValidatedRequest):
    elder_id: str
    language: str

class FamilyNoteRequest(ValidatedRequest):
    elder_id: str
    note: str

class FamilyNoteDeleteRequest(ValidatedRequest):
    elder_id: str
    index: int

class SessionClearRequest(ValidatedRequest):
    elder_id: Optional[str] = None
    session_id: Optional[str] = None

class RAGEvaluationRequest(ValidatedRequest):
    elder_id: str
    queries: list[dict]

class STTEvaluationRequest(ValidatedRequest):
    samples: list[dict]


class ElderPinRequest(ValidatedRequest):
    elder_id: str
    ttl_minutes: int = 480

    @field_validator("ttl_minutes")
    @classmethod
    def validate_ttl_minutes(cls, value: int) -> int:
        if value < 1 or value > 1440:
            raise ValueError("ttl_minutes 必須介於 1 到 1440 分鐘")
        return value


class ElderLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if len(value) != 6 or not value.isascii() or not value.isdigit():
            raise ValueError("PIN 必須是 6 位數字")
        return value


class ElderSessionRevokeRequest(ValidatedRequest):
    elder_id: str


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


def _authenticate_admin(
    credentials: HTTPBasicCredentials | None,
    request: Request,
) -> dict | None:
    users = _load_admin_users()
    if not users:
        client_host = request.client.host if request.client else ""
        if not CARE4U_DEMO_MODE or client_host not in {"127.0.0.1", "::1"}:
            return None
        print(
            f"警告：未設定 ADMIN_PASSWORD / ADMIN_USERS，"
            f"以 demo 身份（role={DEMO_AUTH_ROLE}）登入。"
            f"請設定 ADMIN_PASSWORD 以啟用認證。"
        )
        return {"username": "demo", "role": DEMO_AUTH_ROLE}
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
    def dependency(
        request: Request,
        credentials: HTTPBasicCredentials = Depends(admin_security),
    ):
        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with admin_auth_fail_lock:
            record = admin_auth_fail_counts.get(client_key)
            if record and record.locked_until > now:
                raise HTTPException(
                    status_code=429,
                    detail="登入嘗試過多，請稍後再試",
                )
            if record and record.locked_until:
                admin_auth_fail_counts.pop(client_key, None)

        user = _authenticate_admin(credentials, request)
        if not user:
            with admin_auth_fail_lock:
                record = admin_auth_fail_counts.setdefault(
                    client_key,
                    FailRecord(),
                )
                record.failures += 1
                if record.failures >= ADMIN_AUTH_MAX_FAILURES:
                    record.locked_until = now + ADMIN_AUTH_LOCK_SECONDS
            raise HTTPException(
                status_code=401,
                detail="Admin login required",
                headers={"WWW-Authenticate": "Basic"},
            )
        with admin_auth_fail_lock:
            admin_auth_fail_counts.pop(client_key, None)
        if allowed_roles and user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient admin role")
        return user
    return dependency


require_admin = require_admin_role("admin", "caregiver", "viewer")
require_caregiver = require_admin_role("admin", "caregiver")
require_system_admin = require_admin_role("admin")


def require_elder_token(
    credentials: HTTPAuthorizationCredentials = Depends(elder_security),
) -> ElderIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="需要長者登入 token")
    identity = validate_token(credentials.credentials)
    if identity is None:
        raise HTTPException(status_code=401, detail="長者登入已失效")
    if identity.elder_id not in ALLOWED_ELDER_IDS:
        raise HTTPException(status_code=403, detail="此長者不在允許名單")
    return identity


def _require_allowed_elder(elder_id: str) -> str:
    if elder_id is None:
        raise HTTPException(status_code=422, detail="缺少 elder_id")
    valid_elder_id = validate_elder_id(elder_id)
    if valid_elder_id not in ALLOWED_ELDER_IDS:
        raise HTTPException(status_code=403, detail="此長者不在允許名單")
    return valid_elder_id


def _session_key(elder_id: str, session_id: str = "default", persona_id: str = None) -> str:
    valid_elder_id = validate_elder_id(elder_id)
    valid_session_id = validate_session_id(session_id or "default")
    valid_persona_id = validate_persona_id(persona_id) if persona_id else "profile"
    return f"{valid_elder_id}:{valid_session_id}:{valid_persona_id}"


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


def _evict_stale_sessions(ttl_seconds: int = 3600):
    now = datetime.now()
    stale_keys = [
        key
        for key, decision in decisions.items()
        if (now - decision.last_seen).total_seconds() > ttl_seconds
    ]
    for key in stale_keys:
        decision = decisions.pop(key)
        clear_agent(decision.elder_id, session_id=decision.session_id)

    overflow = len(decisions) - MAX_SESSIONS
    if overflow > 0:
        oldest_keys = sorted(
            decisions,
            key=lambda key: decisions[key].last_seen,
        )[:overflow]
        for key in oldest_keys:
            decision = decisions.pop(key)
            clear_agent(decision.elder_id, session_id=decision.session_id)


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
        loop = asyncio.get_running_loop()
        tone = await loop.run_in_executor(
            None,
            llm.generate_persona_tone,
            persona.get("relation", ""),
            persona.get("name", ""),
            language_text,
            persona.get("personality", []),
            persona.get("habits", []),
        )

        if not memory.set_persona_field(elder_id, persona_id, "tone", tone):
            raise RuntimeError("說話風格儲存失敗")
        print(f"說話風格生成完成：{persona.get('name', '')} → {tone[:30]}...")

    except Exception as e:
        print(f"說話風格生成失敗：{e}")


# ------------------------------------------------------------------
# Static pages
# ------------------------------------------------------------------

def read_root():
    return FileResponse("frontend/index.html")


def admin_page(_: dict = Depends(require_admin)):
    return FileResponse("frontend/admin.html")


# ------------------------------------------------------------------
# Elder authentication
# ------------------------------------------------------------------

def get_system_mode(request: Request):
    client_host = request.client.host if request.client else ""
    return {
        "demo_mode": (
            CARE4U_DEMO_MODE
            and client_host in {"127.0.0.1", "::1"}
        )
    }


def list_allowed_elders(_: dict = Depends(require_caregiver)):
    memory = VectorMemoryStore()
    elders = []
    for elder_id in sorted(ALLOWED_ELDER_IDS):
        profile = memory.get_profile(elder_id) or {}
        elders.append({
            "elder_id": elder_id,
            "name": profile.get("name") or elder_id,
        })
    return {"elders": elders}


def preview_elder_id(name: str = Query(...), _: dict = Depends(require_caregiver)):
    """預覽根據姓名自動產生的 elder_id（不實際建立）。"""
    if not name or not name.strip():
        raise HTTPException(status_code=422, detail="姓名不得為空")
    elder_id = generate_elder_id(name.strip())
    return {"elder_id": elder_id, "name": name.strip()}


def create_elder(req: CreateElderRequest, _: dict = Depends(require_caregiver)):
    """新增一位長者：建立 JSON 檔並更新記憶體中的 ALLOWED_ELDER_IDS。"""
    global ALLOWED_ELDER_IDS

    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="姓名不得為空")

    # 決定 elder_id
    if req.elder_id and req.elder_id.strip():
        try:
            elder_id = validate_elder_id(req.elder_id.strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="elder_id 格式不合法（只允許英數字、- 和 _）")
    else:
        elder_id = generate_elder_id(name)

    # 檢查是否已存在
    target_path = _ELDERS_DATA_DIR / f"{elder_id}.json"
    if target_path.exists():
        raise HTTPException(status_code=409, detail=f"elder_id {elder_id} 已存在")

    # 組建 personas：預設 AI 助理
    default_honorific = "爺爺" if req.gender == "male" else "奶奶"
    personas: dict = {
        "ai": {
            "name": "AI 助理",
            "voice_engine": "edge",
            "voice_path": None,
            "honorific": default_honorific,
            "tone": f"像耐心的照護助理，親切溫和地陪伴{name}{default_honorific}。",
            "avatar_path": "ai_assistant_nobg.png",
            "is_deceased": False,
        }
    }
    for m in (req.family_members or []):
        relation = (m.get("relation") or "").strip()
        member_name = (m.get("name") or "").strip()
        if not relation or not member_name:
            continue
        pid = f"family_{len(personas)}"
        personas[pid] = {
            "name": member_name,
            "relation": relation,
            "voice_engine": "edge",
            "voice_path": None,
            "honorific": default_honorific,
            "language": "mandarin",
            "personality": [],
            "habits": [],
            "tone": f"你是{name}的{relation}{member_name}，語氣親切自然。",
            "avatar_path": "ai_assistant_nobg.png",
            "is_deceased": False,
            "shared_memories": "",
            "current_status": "",
            "forbidden_topics": "",
        }

    # 組建傳記欄位
    biography_content = (req.biography or "").strip()
    biography_dict = {
        "content": biography_content,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources": ["admin_created"],
        "manually_edited": bool(biography_content),
    }

    # 組建完整 profile
    profile: dict = {
        "elder_id": elder_id,
        "name": name,
        "gender": req.gender,
        "cognitive_status": req.cognitive_status,
        "persona": {
            "former_job": req.job or "",
            "tone_preference": "",
            "hobbies": req.hobbies or [],
        },
        "health_notes": {
            "sensitivity": [],
            "diet": "",
        },
        "personas": personas,
        "active_persona": "ai",
        "recent_events": [],
        "memory_summary": {"content": "", "updated_at": "", "based_on_events": 0},
        "elder_biography": biography_dict,
        "biography_usage_count": 0,
        "family_notes": [],
    }
    if req.birth_year:
        profile["birth_year"] = req.birth_year
    if req.hometown:
        profile["hometown"] = req.hometown

    # 寫入 JSON
    _ELDERS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        target_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入長者資料失敗：{e}")

    # 更新記憶體中的允許清單（立即生效，不需重啟）
    ALLOWED_ELDER_IDS.add(elder_id)

    return {
        "success": True,
        "elder_id": elder_id,
        "name": name,
        "message": f"長者 {name}（{elder_id}）建立成功",
    }


def biography_preview_new(req: BiographyPreviewRequest, _: dict = Depends(require_caregiver)):
    """為尚未建檔的新長者生成傳記草稿（Tavily 只搜時代文化脈絡）。"""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="姓名不得為空")

    search = SearchService()
    biography = search.generate_biography_for_new_elder(
        name=name,
        gender=req.gender,
        birth_year=req.birth_year,
        hometown=req.hometown or "",
        job=req.job or "",
        hobbies=req.hobbies or [],
        family_members=req.family_members or [],
        hints=req.hints or "",
    )
    if not biography or len(biography) < 30:
        raise HTTPException(status_code=500, detail="傳記草稿生成失敗，請稍後再試")

    return {
        "success": True,
        "biography": biography,
        "message": "傳記草稿已生成，請確認內容後再儲存。",
    }


def _event_datetime_value(event: dict) -> str:
    return f"{event.get('date', '')} {event.get('time', '')}".strip()


def _event_level(event: dict) -> int:
    level = event.get("escalation_level")
    if isinstance(level, int):
        return level
    tags = set(event.get("topic_tags") or [])
    text = event.get("event", "")
    if "緊急警報" in tags or "胸痛" in text or "呼吸困難" in text:
        return 3
    if "安全警報" in tags or "趨勢警報" in tags or "跌倒" in text or "頭暈" in text:
        return 2
    if event.get("sentiment") == "negative" or "情緒" in tags:
        return 1
    return 0


def get_admin_dashboard(_: dict = Depends(require_caregiver)):
    memory = VectorMemoryStore()
    today = datetime.now().strftime("%Y-%m-%d")
    elders = []
    alerts = []
    conversations = []
    today_conversation_count = 0

    for elder_id in ALLOWED_ELDER_IDS:
        profile = memory.get_profile(elder_id) or {}
        elder_name = profile.get("name") or elder_id
        events = profile.get("recent_events") or []
        today_events = [event for event in events if event.get("date") == today]
        today_conversation_count += len(today_events)

        alert_count = 0
        for event in events:
            level = _event_level(event)
            if level >= 2:
                alert_count += 1
                alerts.append({
                    "elder_id": elder_id,
                    "elder_name": elder_name,
                    "level": level,
                    "time": event.get("time") or "",
                    "date": event.get("date") or "",
                    "content": event.get("event") or event.get("reason") or "",
                    "reason": event.get("reason") or "",
                })

        elders.append({
            "elder_id": elder_id,
            "name": elder_name,
            "today_events": len(today_events),
            "alert_count": alert_count,
            "important_count": len([
                event for event in events
                if float(event.get("importance") or 0) >= 0.7
            ]),
        })

        for key, decision in decisions.items():
            if not key.startswith(f"{elder_id}:"):
                continue
            history = [
                item for item in decision.get_history()
                if item.get("role") in {"user", "model"} and item.get("content")
            ]
            if not history:
                continue
            latest = history[-1]
            conversations.append({
                "elder_id": elder_id,
                "elder_name": elder_name,
                "session_id": key.split(":", 1)[1],
                "speaker": "長者" if latest.get("role") == "user" else "AI",
                "summary": latest.get("content", "")[:80],
                "message_count": len(history),
            })

    alerts.sort(
        key=lambda item: (item.get("date") or "", item.get("time") or ""),
        reverse=True,
    )
    events_sorted = sorted(
        (
            {
                "elder_id": elder_id,
                "elder_name": (memory.get_profile(elder_id) or {}).get("name") or elder_id,
                "time": event.get("time") or "",
                "date": event.get("date") or "",
                "content": event.get("event") or "",
                "level": _event_level(event),
            }
            for elder_id in ALLOWED_ELDER_IDS
            for event in ((memory.get_profile(elder_id) or {}).get("recent_events") or [])
        ),
        key=lambda item: (item["date"], item["time"]),
        reverse=True,
    )
    recent_conversations = conversations[:5] or [
        item for item in events_sorted
        if item.get("content")
    ][:5]

    return {
        "date": today,
        "elder_count": len(elders),
        "today_conversation_count": today_conversation_count,
        "pending_alert_count": len(alerts),
        "recent_alerts": alerts[:5],
        "recent_conversations": recent_conversations[:5],
        "elders": elders,
    }


def create_elder_pin(
    req: ElderPinRequest,
    _: dict = Depends(require_caregiver),
):
    if req.elder_id not in ALLOWED_ELDER_IDS:
        raise HTTPException(status_code=403, detail="此長者不在允許名單")
    pin, session = issue_pin(req.elder_id, req.ttl_minutes)
    return {
        "pin": pin,
        "elder_id": req.elder_id,
        "expires_at": session.expires_at.isoformat(),
    }


def elder_login(req: ElderLoginRequest, request: Request):
    client_key = request.client.host if request.client else "unknown"
    try:
        token, session = login_with_pin(req.pin, client_key)
    except LoginRateLimitedError:
        raise HTTPException(
            status_code=429,
            detail="PIN 嘗試次數過多，請稍後再試",
        )
    except InvalidPinError:
        raise HTTPException(status_code=401, detail="PIN 無效或已使用")
    if session.elder_id not in ALLOWED_ELDER_IDS:
        revoke_elder(session.elder_id)
        raise HTTPException(status_code=403, detail="此長者不在允許名單")
    return {
        "elder_token": token,
        "elder_id": session.elder_id,
        "expires_at": session.expires_at.isoformat(),
    }


def revoke_elder_session(
    req: ElderSessionRevokeRequest,
    _: dict = Depends(require_caregiver),
):
    removed_pins, removed_tokens = revoke_elder(req.elder_id)
    _reset_elder_state(req.elder_id)
    return {
        "success": True,
        "elder_id": req.elder_id,
        "removed_pins": removed_pins,
        "removed_tokens": removed_tokens,
    }


# ------------------------------------------------------------------
# Session management
# ------------------------------------------------------------------

def switch_elder(
    req: GreetRequest,
    _: dict = Depends(require_caregiver),
):
    try:
        _reset_elder_state(req.elder_id, req.session_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Conversation
# ------------------------------------------------------------------

async def _run_background_image(
    task_id: str,
    decision: Decision,
    message: str,
):
    try:
        loop = asyncio.get_running_loop()
        image, caption = await loop.run_in_executor(
            None,
            decision._run_image_gen,
            message,
        )
        _update_background_result(task_id, {
            "image_status": "complete",
            "image": image,
            "image_caption": caption,
        })
    except Exception as e:
        _update_background_result(task_id, {
            "image_status": "failed",
            "image_error": str(e),
        })


async def _run_background_health(
    task_id: str,
    decision: Decision,
    message: str,
):
    try:
        loop = asyncio.get_running_loop()
        health_info = await loop.run_in_executor(
            None,
            decision._run_health_search,
            message,
        )
        _update_background_result(task_id, {
            "health_status": "complete",
            "health_info": health_info,
        })
    except Exception as e:
        _update_background_result(task_id, {
            "health_status": "failed",
            "health_error": str(e),
        })


def greet(req: GreetRequest):
    try:
        elder_id = _require_allowed_elder(req.elder_id)
        return get_decision(
            elder_id,
            req.session_id,
            req.persona_id,
        ).greet()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _next_stream_event(iterator):
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None


async def chat(req: ChatRequest, stream: bool = Query(False)):
    try:
        elder_id = _require_allowed_elder(req.elder_id)
        _evict_stale_sessions()
        decision = get_decision(
            elder_id,
            req.session_id,
            req.persona_id,
        )
        if stream:
            async def event_stream():
                async with decision._lock:
                    iterator = decision.stream_chat(
                        req.message,
                        req.speed_emotion,
                    )
                    loop = asyncio.get_running_loop()
                    while True:
                        has_event, event = await loop.run_in_executor(
                            None,
                            _next_stream_event,
                            iterator,
                        )
                        if not has_event:
                            break
                        if event.get("type") == "done":
                            event["done"] = True
                            event.pop("type", None)
                            event["background_task_id"] = None
                            if event.get("escalation_level", 0) < 2:
                                task_id = _reserve_background_result(elder_id)
                                if task_id:
                                    asyncio.create_task(
                                        _run_background_image(
                                            task_id,
                                            decision,
                                            req.message,
                                        )
                                    )
                                    asyncio.create_task(
                                        _run_background_health(
                                            task_id,
                                            decision,
                                            req.message,
                                        )
                                    )
                                    event["background_task_id"] = task_id
                        else:
                            event = {
                                "chunk": event.get("chunk", ""),
                                "done": False,
                            }
                        yield (
                            "data: "
                            + json.dumps(event, ensure_ascii=False)
                            + "\n\n"
                        )

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        async with decision._lock:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                decision.chat,
                req.message,
                req.speed_emotion,
            )
        result["background_task_id"] = None
        if result.get("escalation_level", 0) < 2:
            task_id = _reserve_background_result(elder_id)
            if task_id:
                asyncio.create_task(
                    _run_background_image(task_id, decision, req.message)
                )
                asyncio.create_task(
                    _run_background_health(task_id, decision, req.message)
                )
                result["background_task_id"] = task_id
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _consume_background_result(
    task_id: str,
    owner_key: str | None = None,
):
    with chat_background_results_lock:
        result = chat_background_results.get(task_id)
        if result is None:
            raise HTTPException(status_code=404, detail="找不到背景任務")
        if owner_key is not None and result.get("_owner_token") != owner_key:
            raise HTTPException(status_code=404, detail="找不到背景任務")
        all_done = _background_all_done(result)
        response = {
            key: value
            for key, value in result.items()
            if not key.startswith("_")
        }
        response["all_done"] = all_done
        if all_done:
            chat_background_results.pop(task_id, None)
        return response


def get_chat_background_result(
    task_id: str,
    _: dict = Depends(require_caregiver),
):
    return _consume_background_result(task_id)


# ------------------------------------------------------------------
# Speech I/O
# ------------------------------------------------------------------

async def speech_to_text(audio: UploadFile = File(...)):
    try:
        await ensure_stt_pool()
        audio_bytes = await audio.read()
        stt_instance = await stt_pool_lock.get()
        try:
            loop = asyncio.get_running_loop()
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


def admin_me(user: dict = Depends(require_admin)):
    return user


def list_sessions(_: dict = Depends(require_caregiver)):
    return {"sessions": _session_rows(), "count": len(decisions)}


def clear_sessions(req: SessionClearRequest, _: dict = Depends(require_system_admin)):
    if req.elder_id:
        _reset_elder_state(req.elder_id, req.session_id)
    else:
        for key in list(decisions):
            decision = decisions.pop(key)
            clear_agent(decision.elder_id, session_id=decision.session_id)
    return {"success": True, "sessions": _session_rows()}


def evaluate_rag(req: RAGEvaluationRequest, _: dict = Depends(require_caregiver)):
    try:
        from backend.tools.rag_evaluation import evaluate_rag_queries
        return evaluate_rag_queries(req.elder_id, req.queries)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def evaluate_stt_transcripts(req: STTEvaluationRequest, _: dict = Depends(require_caregiver)):
    try:
        from backend.tools.stt_corpus_eval import evaluate_transcripts
        return evaluate_transcripts(req.samples)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_stt_status(_: dict = Depends(require_admin)):
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


async def _synthesize_speech(req: TTSRequest, elder_id: str | None):
    try:
        service = tts
        if elder_id:
            memory = VectorMemoryStore()
            profile = memory.get_profile(elder_id)
            personas = profile.get("personas", {}) if profile else {}
            active_id = req.persona_id or (profile.get("active_persona", "ai") if profile else "ai")
            active = personas.get(active_id, personas.get("ai", {}))
            voice_path = active.get("voice_path")
            engine = TTSService.normalize_engine(
                active.get("voice_engine", "xtts")
            )

            service = TTSService(voice="zh-TW-HsiaoChenNeural")
            if engine != "edge":
                service.set_engine(engine, voice_path)
            else:
                service.reset_engine()

        loop = asyncio.get_running_loop()
        audio_bytes = await loop.run_in_executor(None, service.synthesize, req.text, req.emotion)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS 失敗")
        media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
        return Response(content=audio_bytes, media_type=media_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def text_to_speech(
    req: TTSRequest,
    _: dict = Depends(require_caregiver),
):
    return await _synthesize_speech(req, req.elder_id)


async def elder_text_to_speech(
    req: TTSRequest,
):
    elder_id = _require_allowed_elder(req.elder_id)
    return await _synthesize_speech(req, elder_id)


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


def get_history(elder_id: str, _: dict = Depends(require_caregiver)):
    # Prefer live in-memory history (active session).
    key = next((k for k in decisions if k.startswith(f"{elder_id}:")), None)
    if key:
        return {"history": decisions[key].get_history()}
    # Fallback: read persisted conversation from JSON so admin can see history
    # even when no elder session is currently active.
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        # Try all known personas in priority order: active_persona first, then "ai".
        personas_to_try: list[str] = []
        active = profile.get("active_persona") if profile else None
        if active:
            personas_to_try.append(active)
        if "ai" not in personas_to_try:
            personas_to_try.append("ai")
        for pid in personas_to_try:
            hist = memory.load_conversation(elder_id, pid)
            if hist:
                return {"history": hist}
    except Exception as e:
        print(f"get_history fallback 失敗：{e}")
    return {"history": []}


def get_safety(elder_id: str, _: dict = Depends(require_caregiver)):
    try:
        return get_decision(elder_id).get_safety_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def acknowledge_safety_event(
    elder_id: str,
    index: int = ApiPath(..., ge=0),
    _: dict = Depends(require_caregiver),
):
    try:
        memory = VectorMemoryStore()
        if not memory.acknowledge_event_at(elder_id, index):
            raise HTTPException(status_code=404, detail="安全事件不存在")
        _reset_elder_state(elder_id)
        return {"success": True, "elder_id": elder_id, "index": index}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AcknowledgeByTagRequest(ValidatedRequest):
    tag: str


def acknowledge_safety_events_by_tag(
    elder_id: str,
    req: AcknowledgeByTagRequest,
    _: dict = Depends(require_caregiver),
):
    try:
        memory = VectorMemoryStore()
        count = memory.acknowledge_events_by_tag(elder_id, req.tag)
        _reset_elder_state(elder_id)
        return {"success": True, "elder_id": elder_id, "tag": req.tag, "acknowledged_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_agent_logs(_: dict = Depends(require_caregiver)):
    from backend.agents.decision import get_logs
    return {"logs": get_logs()}


async def save_profile(req: ElderProfileUpdate, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        updated = memory.update_basic_fields(req.elder_id, {
            "name": req.name,
            "gender": req.gender,
            "cognitive_status": req.cognitive_status,
            "persona": {
                "former_job": req.former_job,
                "tone_preference": req.tone_preference,
                "hobbies": [h.strip() for h in req.hobbies.split("、") if h.strip()],
            },
            "health_notes": {
                "sensitivity": [s.strip() for s in req.sensitivity.split("、") if s.strip()],
                "diet": req.diet,
            },
        })
        if not updated:
            raise RuntimeError("長者資料儲存失敗")
        if req.active_persona:
            if not memory.set_active_persona(req.elder_id, req.active_persona):
                raise HTTPException(status_code=400, detail="預設陪伴者不存在")
        _reset_elder_state(req.elder_id)
        return {"success": True, "message": f"{req.name} 的資料已儲存"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def save_biography(req: BiographyUpdateRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        biography = {
            "content": req.biography,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": req.sources if req.sources is not None else [],
            "manually_edited": True,
        }
        if memory.set_biography(
            req.elder_id,
            biography,
            preserve_sources=req.sources is None,
        ) != "updated":
            raise RuntimeError("生平資料儲存失敗")

        _reset_elder_state(req.elder_id)
        return {"success": True, "message": "生平資料已儲存"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Personas
# ------------------------------------------------------------------

def get_personas(elder_id: str, _: dict = Depends(require_admin)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")
        return {
            "personas": profile.get("personas", {}),
            "active_persona": profile.get("active_persona", "ai"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def add_persona(req: PersonaAddRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        persona = {
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
        persona_id = memory.add_persona_auto(req.elder_id, persona)
        if not persona_id:
            raise RuntimeError("人格資料儲存失敗")

        asyncio.create_task(_generate_persona_tone(req.elder_id, persona_id))

        _reset_elder_state(req.elder_id)
        return {"success": True, "message": f"已新增：{req.name}", "persona_id": persona_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def delete_persona(req: PersonaDeleteRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        if req.persona_id == "ai":
            raise HTTPException(status_code=400, detail="不能刪除 AI 助理")

        if req.persona_id not in profile.get("personas", {}):
            raise HTTPException(status_code=404, detail="找不到此人格")

        if not memory.delete_persona(req.elder_id, req.persona_id):
            raise RuntimeError("人格資料刪除失敗")
        _reset_elder_state(req.elder_id)
        return {"success": True, "message": "已刪除人格"}

    except KeyError:
        raise HTTPException(status_code=404, detail="找不到此人格")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def switch_persona(req: PersonaSwitchRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        personas = profile.get("personas", {})
        if req.persona_id not in personas:
            raise HTTPException(status_code=404, detail="找不到此人格")

        if not memory.set_active_persona(req.elder_id, req.persona_id):
            raise RuntimeError("啟用人格失敗")
        _reset_elder_state(req.elder_id)
        return {
            "success": True,
            "message": f"已切換到：{personas[req.persona_id]['name']}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def upload_voice(
    elder_id: str = Form(...),
    persona_id: str = Form(...),
    voice: UploadFile = File(...),
    _: dict = Depends(require_caregiver),
):
    try:
        elder_id = validate_elder_id(elder_id)
        persona_id = validate_persona_id(persona_id)
        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        persona = profile.get("personas", {}).get(persona_id) if profile else None
        if persona is None:
            raise HTTPException(status_code=404, detail="找不到此人格")

        voices_dir = Path(f"backend/data/elders/{elder_id}_voices")
        voices_dir.mkdir(parents=True, exist_ok=True)
        voice_path = voices_dir / f"{persona_id}.wav"
        temp_path = voice_path.with_name(
            f".{voice_path.name}.{secrets.token_hex(8)}.tmp"
        )
        old_path = persona.get("voice_path")
        old_engine = persona.get("voice_engine")
        metadata_changed = False
        try:
            with open(temp_path, "wb") as f:
                shutil.copyfileobj(voice.file, f)

            path_updated = memory.set_persona_field(
                elder_id,
                persona_id,
                "voice_path",
                str(voice_path),
            )
            engine_updated = path_updated and memory.set_persona_field(
                elder_id,
                persona_id,
                "voice_engine",
                "xtts",
            )
            metadata_changed = path_updated or engine_updated
            if not path_updated or not engine_updated:
                raise RuntimeError("語音樣本資料儲存失敗")
            os.replace(temp_path, voice_path)
        except Exception:
            if metadata_changed:
                memory.set_persona_field(
                    elder_id, persona_id, "voice_path", old_path
                )
                memory.set_persona_field(
                    elder_id, persona_id, "voice_engine", old_engine
                )
            raise
        finally:
            temp_path.unlink(missing_ok=True)

        _reset_elder_state(elder_id)
        return {"success": True, "message": "語音樣本已上傳", "path": str(voice_path)}

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def background_candidates(req: BackgroundCandidateRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

        search = SearchService()
        result = search.search_background_candidates(profile, req.extra_keywords)
        return {
            "success": True,
            "queries": result.get("queries", []),
            "candidates": result.get("candidates", []),
            "message": result.get("message", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def biography_draft(req: BiographyDraftRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")

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
            raise HTTPException(status_code=500, detail="生平草稿生成失敗")

        return {
            "success": True,
            "message": "已產生生平草稿，請確認後再儲存。",
            "biography": biography,
            "sources": [
                {"title": s.get("title", ""), "url": s.get("url", "")}
                for s in sources
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def upload_avatar(
    elder_id: str = Form(...),
    persona_id: str = Form(...),
    avatar: UploadFile = File(...),
    _: dict = Depends(require_caregiver),
):
    try:
        elder_id = validate_elder_id(elder_id)
        persona_id = validate_persona_id(persona_id)
        suffix = Path(avatar.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=400, detail="只支援 png、jpg、jpeg、webp")

        memory = VectorMemoryStore()
        profile = memory.get_profile(elder_id)
        persona = profile.get("personas", {}).get(persona_id) if profile else None
        if persona is None:
            raise HTTPException(status_code=404, detail="找不到此人格")

        avatars_dir = Path("frontend/avatars/personas")
        avatars_dir.mkdir(parents=True, exist_ok=True)
        avatar_filename = f"{elder_id}_{persona_id}{suffix}"
        avatar_path = avatars_dir / avatar_filename
        temp_path = avatar_path.with_name(
            f".{avatar_path.name}.{secrets.token_hex(8)}.tmp"
        )
        old_avatar_path = persona.get("avatar_path")
        metadata_changed = False
        try:
            with open(temp_path, "wb") as f:
                shutil.copyfileobj(avatar.file, f)

            metadata_changed = memory.set_persona_field(
                elder_id,
                persona_id,
                "avatar_path",
                f"personas/{avatar_filename}",
            )
            if not metadata_changed:
                raise RuntimeError("陪伴者照片資料儲存失敗")
            os.replace(temp_path, avatar_path)
        except Exception:
            if metadata_changed:
                memory.set_persona_field(
                    elder_id,
                    persona_id,
                    "avatar_path",
                    old_avatar_path,
                )
            raise
        finally:
            temp_path.unlink(missing_ok=True)

        _reset_elder_state(elder_id)
        return {
            "success": True,
            "message": "陪伴者照片已上傳",
            "avatar_path": f"personas/{avatar_filename}",
        }

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Family notes
# ------------------------------------------------------------------

def add_family_note(req: FamilyNoteRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")
        if not memory.append_family_note(req.elder_id, {
            "note": req.note,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "added_by": "照護人員",
        }):
            raise RuntimeError("家屬備註儲存失敗")
        updated_profile = memory.get_profile(req.elder_id)
        return {"success": True, "family_notes": updated_profile.get("family_notes", [])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def delete_family_note(req: FamilyNoteDeleteRequest, _: dict = Depends(require_caregiver)):
    try:
        memory = VectorMemoryStore()
        profile = memory.get_profile(req.elder_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到長者資料")
        if not memory.delete_family_note_at(req.elder_id, req.index):
            raise RuntimeError("家屬備註刪除失敗")
        updated_profile = memory.get_profile(req.elder_id)
        return {"success": True, "family_notes": updated_profile.get("family_notes", [])}
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_elder_profile(
    elder_id: str = Query(...),
):
    elder_id = _require_allowed_elder(elder_id)
    profile = VectorMemoryStore().get_profile(elder_id)
    if not profile or not profile.get("name"):
        raise HTTPException(status_code=404, detail="找不到長者資料")
    return profile


def get_elder_personas(
    elder_id: str = Query(...),
):
    elder_id = _require_allowed_elder(elder_id)
    profile = VectorMemoryStore().get_profile(elder_id)
    if not profile:
        raise HTTPException(status_code=404, detail="找不到長者資料")
    return {
        "personas": profile.get("personas", {}),
        "active_persona": profile.get("active_persona", "ai"),
    }


def get_elder_background_result(
    task_id: str,
    elder_id: str = Query(...),
):
    elder_id = _require_allowed_elder(elder_id)
    return _consume_background_result(task_id, elder_id)


from backend.routers.admin import build_router as build_admin_router
from backend.routers.chat import build_router as build_chat_router
from backend.routers.elder_session import build_router as build_elder_session_router
from backend.routers.persona import build_router as build_persona_router
from backend.routers.profile import build_router as build_profile_router
from backend.routers.speech import build_router as build_speech_router


app.include_router(
    build_chat_router(
        {
            "read_root": read_root,
            "switch_elder": switch_elder,
            "greet": greet,
            "chat": chat,
            "get_chat_background_result": get_chat_background_result,
        }
    )
)
app.include_router(
    build_profile_router(
        {
            "get_profile": get_profile,
            "get_history": get_history,
            "get_safety": get_safety,
            "acknowledge_safety_event": acknowledge_safety_event,
            "acknowledge_safety_events_by_tag": acknowledge_safety_events_by_tag,
            "get_agent_logs": get_agent_logs,
            "save_profile": save_profile,
            "save_biography": save_biography,
            "background_candidates": background_candidates,
            "biography_draft": biography_draft,
            "biography_preview_new": biography_preview_new,
            "add_family_note": add_family_note,
            "delete_family_note": delete_family_note,
        }
    )
)
app.include_router(
    build_persona_router(
        {
            "get_personas": get_personas,
            "add_persona": add_persona,
            "delete_persona": delete_persona,
            "switch_persona": switch_persona,
            "upload_voice": upload_voice,
            "upload_avatar": upload_avatar,
        }
    )
)
app.include_router(
    build_admin_router(
        {
            "admin_page": admin_page,
            "admin_me": admin_me,
            "get_admin_dashboard": get_admin_dashboard,
            "list_sessions": list_sessions,
            "clear_sessions": clear_sessions,
            "evaluate_rag": evaluate_rag,
            "evaluate_stt_transcripts": evaluate_stt_transcripts,
        }
    )
)
app.include_router(
    build_speech_router(
        {
            "speech_to_text": speech_to_text,
            "get_stt_status": get_stt_status,
            "text_to_speech": text_to_speech,
            "set_stt_language": set_stt_language,
        }
    )
)
app.include_router(
    build_elder_session_router(
        {
            "get_system_mode": get_system_mode,
            "list_allowed_elders": list_allowed_elders,
            "preview_elder_id": preview_elder_id,
            "create_elder": create_elder,
            "create_elder_pin": create_elder_pin,
            "revoke_elder_session": revoke_elder_session,
            "elder_login": elder_login,
            "get_elder_profile": get_elder_profile,
            "get_elder_personas": get_elder_personas,
            "elder_text_to_speech": elder_text_to_speech,
            "get_elder_background_result": get_elder_background_result,
        }
    )
)
