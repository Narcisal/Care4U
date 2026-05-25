# AI Care U

成功大學資工系專題：面向高齡照護情境的 AI 陪伴與照護人員後台系統。

AI Care U 以「長者聊天前台」和「照護人員後台」為核心。長者可以和不同家人陪伴者人格對話；後台則讓照護人員管理長者資料、陪伴者、家人補充資訊、iSafe 安全事件、Decision 任務與 Agent 紀錄。

## 目前展示範圍

- 3 位長者 demo profile：`W001`、`C001`、`L001`
- 每位長者 4 位陪伴者人格
- 前台長者友善聊天介面
- 後台長者資料建檔、家人補充資訊、生平資料、陪伴者管理
- 後台可替陪伴者上傳照片與 `.wav` 聲音樣本
- TTS 流程：XTTS 優先、edge-tts 後援、Windows SAPI 離線保底
- iSafe 情緒與安全分級，可展示一般情緒、低風險提醒與高風險跌倒警報
- Decision 任務排程 demo，可切換啟用/暫停狀態
- Agent 監控與對話紀錄後台
- Demo mode：沒有 Gemini API key、PostgreSQL、Tavily、XTTS 或 GPU 時仍可跑基本展示

目前刻意不做：精油 RAG、臉部情緒偵測、YOLO 視覺偵測、硬體巡檢與定位。

## 專案結構

```text
Care4U_codex/
  backend/
    main.py                  FastAPI 入口與 API endpoints
    agents/
      decision.py            協調 MagicAI、iSafe、圖片與健康搜尋
      magic_ai.py            對話代理與記憶整合
      i_safe.py              情緒、安全分級、趨勢警報
    services/
      llm_service.py         Gemini / demo fallback
      stt_service.py         Whisper / Breeze ASR
      tts_service.py         XTTS、edge-tts、Windows SAPI fallback
      embedding_service.py   Gemini embedding / demo fallback
    memory/
      json_store.py          JSON profile/event 儲存
      vector_store.py        PostgreSQL + pgvector optional 儲存
    tools/
      health_search.py       健康主題搜尋
      image_gen.py           懷舊場景圖片生成
      search_service.py      生平資料搜尋
    data/elders/             長者 demo JSON
  frontend/
    index.html               長者聊天前台
    admin.html               照護人員後台
    app.js                   前台互動邏輯
    avatars/                 demo 頭像素材
  demo_script.md             展示腳本
  delivery_status.md         交付檢查表與待做事項
  future_plan.md             下一階段規劃
```

## Demo 長者

| Elder ID | 姓名 | 展示重點 |
|---|---|---|
| `W001` | 王大明 | 退休工程師、鄧麗君、象棋、安全警報 demo |
| `C001` | 陳秀英 | 退休老師、園藝、料理、家庭陪伴 |
| `L001` | 林月琴 | 裁縫背景、輕度失智照護情境 |

每位長者都應維持 4 位陪伴者人格，這是教授目前要求的主要展示點。

## 快速啟動

### 1. 建立環境

```powershell
pip install -r requirements.txt
```

如果本機 `python` / `py` 指令不可用，這台機器目前可用：

```powershell
C:\Users\user\bin\py.cmd
```

### 2. 設定 `.env`

複製 `.env.example` 成 `.env`，再視情況填入 API key。

最小 demo 可使用：

```env
CARE4U_DEMO_MODE=true
DB_ENABLED=false
STT_POOL_SIZE=1
XTTS_URL=http://localhost:8082
```

### 3. 啟動後端

```powershell
C:\Users\user\bin\py.cmd -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

或在一般 Python 環境：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 4. 開啟頁面

- 前台：`http://127.0.0.1:8000/`
- 後台：`http://127.0.0.1:8000/admin`

## XTTS 語音克隆

系統會在陪伴者有 `voice_path` 時優先呼叫 XTTS。後台可上傳陪伴者 `.wav` 聲音樣本；沒有聲音樣本或 XTTS 不可用時，會自動改用 edge-tts，再失敗則使用 Windows SAPI 離線保底。

展示前請務必製作並上傳 `.wav`，否則只能展示 TTS fallback，無法展示聲音克隆效果。

預設 XTTS API：

```env
XTTS_URL=http://localhost:8082
```

## 重要環境變數

| 變數 | 預設/建議 | 說明 |
|---|---|---|
| `CARE4U_DEMO_MODE` | `true` | 沒有外部 API 時使用 demo fallback |
| `GEMINI_API_KEY` | 空或真實 key | Gemini 對話、摘要、embedding |
| `TAVILY_API_KEY` | 空或真實 key | 生平資料與健康搜尋 |
| `DB_ENABLED` | `false` | 是否啟用 PostgreSQL / pgvector |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5433` | PostgreSQL port |
| `DB_NAME` | `aicaeru` | PostgreSQL database |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | 空 | PostgreSQL password |
| `STT_POOL_SIZE` | `1` | Whisper worker 數量，demo 建議 1 |
| `STT_MODEL_SIZE` | `medium` | Whisper model size |
| `STT_DEVICE` | `cuda` | 可改 `cpu` |
| `XTTS_URL` | `http://localhost:8082` | 主要 XTTS API |
| `BREEZYVOICE_URL` | `http://localhost:8080` | legacy voice service |
| `LUXTTS_URL` | `http://localhost:8081` | optional voice service |

## 展示前檢查

1. 開啟後台 `http://127.0.0.1:8000/admin`
2. 確認 3 位長者都存在
3. 確認每位長者都有 4 位陪伴者
4. 到陪伴者管理上傳照片與 `.wav`
5. 前台選長者並進入聊天
6. 測試安全句：「我頭很暈快跌倒了」
7. 到後台查看 iSafe、對話紀錄、Agent 監控
8. 照 `demo_script.md` 跑一次完整流程

## 開發備註

- FastAPI 啟動時不會立即載入 STT，第一次使用 `/api/stt` 才 lazy-load。
- PostgreSQL 是 optional；`DB_ENABLED=false` 時會使用 JSON profile。
- 後台上傳的語音樣本屬於個資/聲紋資料，不應提交到 Git。
- 後台上傳的家人照片也不應提交到 Git。
- `delivery_status.md` 是目前交付狀態與剩餘工作的主文件。
