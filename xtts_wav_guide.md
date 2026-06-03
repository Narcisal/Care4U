# XTTS WAV Preparation Guide

AI Care U uses XTTS first when a companion persona has an uploaded `.wav` voice sample. If XTTS or the sample is unavailable, the system falls back to edge-tts, then Windows SAPI.

## Ethics and Consent

- Record only with the speaker's clear consent.
- Explain that the voice sample will be used for a capstone demo voice-cloning feature.
- Avoid using a deceased person's real voice unless the family explicitly agrees and the demo context is handled carefully.
- For the final presentation, it is acceptable to use your own placeholder voice samples and clearly say they are demo samples.

## Audio Format

Recommended:

- File type: `.wav`
- Duration: 20 to 40 seconds per persona
- Sample rate: 22050 Hz or 24000 Hz if available
- Channel: mono
- Environment: quiet room, no music, no fan noise
- Speaking style: natural, warm, not exaggerated
- Distance: microphone about 15 to 25 cm from mouth

Avoid:

- Background music
- Echo-heavy rooms
- Multiple speakers in one file
- Very emotional shouting or whispering
- Phone calls with heavy compression if a cleaner recording is available

## File Naming

Use predictable names before uploading:

```text
W001_ai.wav
W001_daughter.wav
W001_son.wav
W001_granddaughter.wav
C001_ai.wav
C001_son.wav
C001_granddaughter.wav
C001_neighbor.wav
L001_ai.wav
L001_daughter.wav
L001_grandson.wav
L001_spouse.wav
```

The admin dashboard stores the uploaded file path into the persona profile, so the original local filename is mainly for your own organization.

## Recording Script

Use one short paragraph per persona. The speaker should read slowly and naturally.

### Neutral Family Sample

```text
爸，我在這裡陪你說說話。你不用急，慢慢講就好。今天如果覺得冷，記得披一件外套。等一下我們也可以聊聊以前的事情，像是你喜歡的歌，或是以前工作時有趣的回憶。
```

### Warm Daughter Sample

```text
爸，是我小玲。我今天想陪你聊聊天。你如果覺得累，就先坐好休息，我會慢慢聽你說。你以前最喜歡聽鄧麗君，也常說下象棋很有趣，我都記得。
```

### Calm Son Sample

```text
爸，我是建宏。我在這裡陪你。你不用擔心，有什麼不舒服就慢慢說，我會提醒照護人員注意。今天我們可以聊工作、聊家裡，也可以聊你以前當工程師的故事。
```

### Grandchild Sample

```text
阿公，我是安安。我來陪你說話了。你慢慢講，我都有在聽。你如果想聽歌、想聊天，或是想說以前的故事，都可以跟我說，我會一直陪著你。
```

### Careful Dementia-Friendly Sample

```text
媽，我在這裡陪你。你現在很安全，我們慢慢來。你如果忘記事情也沒關係，我會再提醒你一次。先坐著休息，喝一點水，我們一起慢慢說。
```

## Upload Order

1. Open `http://127.0.0.1:8000/admin`.
2. Go to `陪伴者管理`.
3. Select the elder.
4. Choose or create the companion persona.
5. Upload the persona photo first.
6. Upload the `.wav` voice sample.
7. Save/add the persona.
8. Open the elder chat UI and start a conversation with that persona.
9. Check backend logs for XTTS usage.

## Demo Checklist

- At least one persona has a `.wav` sample before final demo.
- The XTTS API server is running at the configured `XTTS_URL`.
- If XTTS is not running, verify that edge-tts or Windows SAPI fallback still speaks.
- Prepare one sentence to explain fallback clearly:

```text
系統會優先使用家人聲音樣本做 XTTS；如果展示環境沒有啟動 XTTS，會自動降級到 edge-tts 或 Windows SAPI，避免語音功能整個失敗。
```

