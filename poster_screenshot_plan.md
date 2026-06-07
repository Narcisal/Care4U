# Poster Screenshot Plan

Use these screenshots for the Results section of the poster. Capture at 1920 x 1080 or higher if possible, then crop cleanly. Avoid showing browser bookmarks, private paths, or temporary testing text.

## Recommended Screenshots

### 1. Elder Companion Entry

- URL: `http://127.0.0.1:8000/?elder=W001`
- State: landing screen before entering chat.
- Show: AI guide on the left, family/persona cards on the right.
- Purpose: demonstrates elder-friendly, low-friction persona selection.

### 2. Elder Chat In Progress

- URL: `http://127.0.0.1:8000/?elder=W001&persona=ai&autostart=1`
- State: active chat screen after greeting.
- Show: large companion avatar, listening/speaking status, simple top switch button.
- Purpose: demonstrates large visual target, voice-first conversation, and companion presence.

### 3. Caregiver Overview

- URL: `http://127.0.0.1:8000/admin`
- Action: open sidebar, select `對話紀錄後台`.
- Show: three elder overview cards.
- Purpose: demonstrates multi-elder caregiver overview.

### 4. Elder Profile and Biography Draft

- URL: `http://127.0.0.1:8000/admin`
- Action: open `長者資料建檔`, scroll to public background/biography area, generate draft if needed.
- Show: profile fields plus biography draft area.
- Purpose: demonstrates caregiver-assisted profile grounding and fallback biography drafting.

### 5. Companion Management

- URL: `http://127.0.0.1:8000/admin`
- Action: open `陪伴者管理`.
- Show: companion cards and upload fields for photo / `.wav`.
- Purpose: demonstrates family-persona setup and XTTS preparation.

### 6. Safety Observation

- URL: `http://127.0.0.1:8000/admin`
- Action: first send this through chat or API: `我頭很暈，快要跌倒了`; then open `安全觀察`.
- Show: high-risk status and recent safety event.
- Purpose: demonstrates iSafe escalation and caregiver visibility.

### 7. Agent Log by Elder

- URL: `http://127.0.0.1:8000/admin`
- Action: open `系統處理紀錄`, choose `王大明`.
- Show: agent status cards, elder filter, session management.
- Purpose: demonstrates session isolation and transparent system processing.

### 8. Memory Retrieval Test

- URL: `http://127.0.0.1:8000/admin`
- Action: open `記憶檢索測試`, press `帶入預設題目`, then `開始測試`.
- Show: hit rate and retrieved memories.
- Purpose: demonstrates that important elder memories can be retrieved during the Windows demo. If the Linux PostgreSQL / pgvector service is running, the same page can be used to compare database-backed retrieval.

### 9. Taiwanese STT Verification

- URL: `http://127.0.0.1:8000/admin`
- Action: open `語音驗證`, press `檢查狀態`, optionally run CER sample.
- Show: STT status and CER evaluation.
- Purpose: demonstrates Taiwanese STT readiness and evaluation path.

## Optional API Setup Before Screenshots

Use UTF-8 when sending Chinese text. PowerShell may corrupt Chinese JSON unless carefully encoded. This Python command creates one safety event for screenshot use:

```powershell
C:\Users\user\bin\py.cmd -c "import json, urllib.request; payload={'elder_id':'W001','message':'我頭很暈，快要跌倒了','speed_emotion':'normal','session_id':'poster-shot','persona_id':'ai'}; data=json.dumps(payload, ensure_ascii=False).encode('utf-8'); req=urllib.request.Request('http://127.0.0.1:8000/api/chat', data=data, headers={'Content-Type':'application/json'}, method='POST'); print(urllib.request.urlopen(req, timeout=60).read().decode('utf-8'))"
```

After screenshots, remove any temporary event if you do not want demo data changed.

## Poster Figure Layout Suggestion

- Largest figure: system architecture diagram.
- Medium figures: elder chat, caregiver overview, safety observation.
- Small figures: RAG evaluation, STT verification, companion upload.
