# AI Care U 交付檢查表

## 目前完成

- 後端可在本機以 FastAPI 啟動。
- 前台可選擇 3 位長者。
- 每位長者都有 4 位陪伴者人格。
- 後台可查看長者資料、對話紀錄、iSafe、Decision、Agent 監控與人格管理。
- 後台可替陪伴者上傳照片與 `.wav` 語音樣本；有語音樣本時優先使用 XTTS。
- TTS 流程目前為 XTTS 優先、edge-tts 後援，並加上 Windows SAPI 離線保底，避免展示時播放 API 直接失敗。
- 後台操作提示已改成一致的 toast 與頁面狀態文字，減少不適合照護現場的彈窗與工程錯誤符號。
- Demo mode 已補上 JSON 歷史記憶 RAG fallback，沒有 PostgreSQL/pgvector 時仍可找回相關舊記憶。
- 重要記憶已加入保留與加權規則，安全事件、家人資訊、人生回憶會更穩定進入長期記憶。
- 前台聊天已加入 session/persona 隔離，同一台後端可支援不同視窗選不同長者或陪伴者。
- 後台支援可選式 Basic Auth；設定 `ADMIN_PASSWORD` 後 `/admin` 會要求登入。
- 台語 STT 已補上 `/api/stt/status` 診斷與 Breeze ASR 切換流程驗證；`/api/stt/language` 已驗證可切到 `tai` 並載入 Breeze ASR 26。正式辨識準確度仍需真人錄音樣本確認。
- 下一階段功能已具備工程骨架：角色式後台權限、session 管理 API、RAG hit-rate 評估 API、台語 STT transcript CER 評估 API。
- 前台已改成「陪你說說話」方向，降低 AI/系統字眼，放大長者可讀文字與主要狀態提示；後台第一層命名也改為照護語言。
- Demo mode 可在沒有 Gemini API key、資料庫或外部服務時跑基本展示。
- iSafe 已有固定測試案例，可展示 Level 0、Level 1、Level 3。
- Decision 任務排程已做成可切換啟用/暫停的 demo 管理狀態。
- 已移除不打算做的精油 RAG、臉部情緒偵測與硬體巡檢預留項。
- 前台聊天泡泡已改用安全 DOM 寫入，避免把使用者或 AI 文字當 HTML 執行。

## 展示前檢查

1. 啟動後端：

```powershell
C:\Users\user\bin\py.cmd -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

2. 開啟前台：

```text
http://127.0.0.1:8000/
```

3. 開啟後台：

```text
http://127.0.0.1:8000/admin
```

4. 前台確認：
   - 王大明、陳秀英、林月琴都能切換。
   - 每位長者都顯示 4 位陪伴者。
   - 選擇陪伴者後能進入聊天。

5. 後台確認：
   - 對話紀錄後台的專題展示總覽有 3 位長者。
   - 每位長者顯示陪伴者 4/4。
   - iSafe 分級測試可以執行。
   - Decision 頁面沒有精油 RAG、臉部偵測或硬體巡檢項目。

6. 展示前最後提醒：
   - 製作並上傳陪伴者 `.wav` 語音樣本，讓 XTTS 優先 TTS 流程可以實際展示。

## 已知待做

| 優先度 | 工作 | 說明 |
|--------|------|------|
| 高 | 展示劇本排練 | 依 `demo_script.md` 跑一次完整流程 |
| 高 | 補齊 XTTS 語音樣本 | 展示前需準備 `.wav`，目前沒有陪伴者 voice sample |
| 低 | 台語語音辨識準確度測試 | API 診斷與 Breeze 載入已驗證；之後需用真人台語錄音測辨識品質 |
| 低 | 後台權限 UI 化 | 後端角色權限已完成，若要展示多人登入可再補 UI 說明或帳號配置 |
| 低 | RAG / STT 評估資料集 | 評估 API 已完成，之後可補正式測資與圖表 |

## 目前不做

- 精油香氛 RAG
- 臉部或面部情緒偵測
- YOLO 視覺偵測
- 硬體巡檢與定位
