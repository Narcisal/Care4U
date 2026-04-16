# AI Care4U — 智慧照護陪伴系統

以 AI 驅動的長照陪伴系統，透過語音對話、情緒感知與個人化記憶，為長者提供有溫度的陪伴服務。

---

## 功能特色

-  語音對話（Faster Whisper STT + Edge-TTS）
-  人格化 AI 陪伴（Gemini 2.5 Flash）
-  情緒偵測與語調調整
-  長者個人化資料建檔
-  照護人員後台與情緒紀錄

---

## 系統需求

- Python 3.10+
- NVIDIA GPU（選用，無 GPU 自動使用 CPU 模式）

---

## 快速開始

**1. 複製專案**
```bash
git clone https://github.com/你的帳號/ai-care-u.git
cd ai-care-u
```

**2. 建立虛擬環境**
```bash
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Mac/Linux
```

**3. 安裝套件**
```bash
pip install -r requirements.txt
```

**4. 設定 API Key**
```bash
cp .env.example .env
# 編輯 .env，填入你的 Gemini API Key
```

**5. 啟動伺服器**
```bash
uvicorn backend.main:app --reload
```

**6. 開啟瀏覽器**
- 長者對話頁面：http://127.0.0.1:8000
- 照護人員後台：http://127.0.0.1:8000/admin

---

## 專案結構
```
ai_care_u/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── agents/
│   │   └── magic_ai.py      # MagicAI 互動代理人
│   ├── services/
│   │   ├── stt_service.py   # Faster Whisper 語音辨識
│   │   ├── tts_service.py   # Edge-TTS 語音輸出
│   │   └── llm_service.py   # Gemini LLM
│   ├── memory/
│   │   ├── memory_manager.py
│   │   └── json_store.py
│   └── data/elders/         # 長者資料
├── frontend/
│   ├── index.html           # 長者對話頁面
│   ├── admin.html           # 照護人員後台
│   └── app.js               # 前端邏輯
└── .env.example
```

---

## 技術架構

| 元件 | 技術 |
|------|------|
| 後端 | FastAPI + Python |
| LLM | Gemini 2.5 Flash |
| 語音辨識 | Faster Whisper |
| 語音輸出 | Edge-TTS |
| 前端 | HTML + Tailwind CSS |

---

## MVP 開發進度

### 已完成
- [x] MagicAI 互動代理人（人格化 System Prompt + 優先順序邏輯）
- [x] 語音對話完整閉環（STT + LLM + TTS）
- [x] 情緒化語調調整（五種情緒對應不同語速音調）
- [x] 長者資料建檔頁面（含家人關係下拉選單）
- [x] 照護人員後台（情緒紀錄 + TTS 語調測試）
- [x] 雙頁面分離（長者端 / 照護人員端）
- [x] 記憶系統抽象層（預留向量資料庫升級接口）

### 下週目標
- [ ] 對話記憶跨 session 保留（目前重啟會消失）
- [ ] 情緒偵測改用 LLM 判斷（取代關鍵字比對）
- [ ] 每次對話前注入近期對話摘要
- [ ] 三隻 Agent 切割（MagicAI / iSafe / Decision）

### 修復或優化
- [ ] 情緒偵測邏輯重複（三個地方各寫一次）
- [ ] TTS 疊音問題（新回應播放前未停止舊音訊）
- [ ] AI 回應期間輸入欄未鎖住
- [ ] CORS 正式環境需限制來源
- [ ] /admin 後台需加入登入保護

### 未來規劃
- [ ] iSafe 感知代理人（YOLO 跌倒偵測 + 臉部情緒）
- [ ] Decision 決策代理人
- [ ] 向量資料庫記憶升級（pgvector）
- [ ] 長短期記憶分層（重要分數機制）
- [ ] 記憶彙整摘要（LLM 定期整理對話）
- [ ] TTS Streaming（邊生成邊播放）