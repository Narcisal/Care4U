const urlParams = new URLSearchParams(window.location.search);
let ELDER_ID = sessionStorage.getItem("care4u_elder_id") || "";
let SELECTED_PERSONA = urlParams.get("persona") || null;
const API_BASE = window.location.origin;
const SESSION_ID = (() => {
    const key = "care4u_session_id";
    let value = sessionStorage.getItem(key);
    if (!value) {
        value = (globalThis.crypto?.randomUUID?.() || `session-${Date.now()}-${Math.random().toString(16).slice(2)}`);
        sessionStorage.setItem(key, value);
    }
    return value;
})();

let chatCount = 0;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let currentPersonaAvatar = "/static/avatars/ai_assistant_nobg.png";
let currentElderAvatar = "/static/avatars/elder_male_nobg.png";

async function elderFetch(path, options = {}) {
    return fetch(`${API_BASE}${path}`, options);
}

function elderQueryPath(path) {
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}elder_id=${encodeURIComponent(ELDER_ID)}`;
}

function elderBody(data = {}) {
    return JSON.stringify({ ...data, elder_id: ELDER_ID });
}

function showLaunchHint() {
    document.getElementById('welcome-screen').style.display = 'flex';
    document.getElementById('main-screen').style.display = 'none';
    const container = document.getElementById('welcome-persona-list');
    if (container) {
        container.innerHTML = `
            <div style="text-align:center;color:#6B5E58;padding:36px;font-size:24px;grid-column:1/-1;line-height:1.8;">
                請透過指定長者連結開啟<br>
                <span style="font-size:18px;color:#A89080;">例如 /?elder=W001</span>
            </div>
        `;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

function safeAvatarSrc(path, fallback = "/static/avatars/ai_assistant_nobg.png") {
    if (!path) return fallback;
    const value = String(path).trim().replaceAll("\\", "/");
    if (/^personas\/[A-Za-z0-9_-]+\.(png|jpg|jpeg|webp)$/i.test(value)) {
        return `/static/avatars/${value}`;
    }
    const filename = value.split("/").pop();
    if (/^[A-Za-z0-9_-]+(?:_bg|_nobg)?\.png$/.test(filename)) {
        return `/static/avatars/${filename}`;
    }
    return fallback;
}

function safeHttpUrl(url) {
    try {
        const parsed = new URL(String(url));
        return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
    } catch {
        return null;
    }
}

function enableButtons() {
    document.getElementById("text-input").removeAttribute("disabled");
    document.getElementById("send-btn").removeAttribute("disabled");
    document.getElementById("hold-talk-btn").removeAttribute("disabled");
}

async function loadElderProfile() {
    if (!ELDER_ID) return;
    try {
        const res = await elderFetch(elderQueryPath("/api/elder/profile"));
        if (!res.ok) throw new Error("profile");
        const profile = await res.json();
        const nameEl = document.getElementById("elder-name-display");
        if (nameEl) nameEl.textContent = profile.name || "未知";
        const elderNameEl = document.getElementById("elder-name");
        if (elderNameEl) elderNameEl.textContent = profile.name || "未知";
    } catch (e) {
        const nameEl = document.getElementById("elder-name-display");
        if (nameEl) nameEl.textContent = "載入失敗";
    }
}

async function switchElder(elderId) {
    if (!elderId || elderId === ELDER_ID) {
        return;
    }

    try {
        ELDER_ID = elderId;
        SELECTED_PERSONA = null;
        sessionStorage.setItem("care4u_elder_id", ELDER_ID);
        window.location.reload();
    } catch (e) {
        console.error("切換長者失敗", e);
        alert(e.message || "切換長者失敗");
    }
}

async function startSession() {
    const btn = document.getElementById("start-btn");
    btn.textContent = "準備中...";
    btn.disabled = true;

    try {
        const res = await elderFetch("/api/greet", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: elderBody({
                session_id: SESSION_ID,
                persona_id: SELECTED_PERSONA
            })
        });
        if (!res.ok) throw new Error("greet");
        const data = await res.json();

        addMessage("ai", data.message);
        enableButtons();
        document.getElementById("text-input").focus();
        btn.textContent = "正在陪你聊天";
        updateEmotionStatus("😊", "正常");
        await speakText(data.message, "normal");

    } catch (e) {
        btn.textContent = "再試一次";
        btn.disabled = false;
        addMessage("system", "剛剛沒有準備好，我們再試一次。");
    }
}

async function sendMessage() {
    const input = document.getElementById("text-input");
    const message = input.value.trim();
    if (!message) return;
    addMessage("user", message);
    input.value = "";
    await processAndRespond(message, "normal");
}

// ── 逐句串流 TTS ─────────────────────────────────────────────────────────────

/** 立刻發 TTS 請求，回傳 Promise<Blob>（不阻塞，後台並行下載） */
function fetchTTSBlob(text) {
    return elderFetch("/api/elder/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: elderBody({ text, emotion: "normal", persona_id: SELECTED_PERSONA })
    }).then(r => r.ok ? r.blob() : null).catch(() => null);
}

/** 從 buffer 抽取所有「句尾符號結尾」的完整句子，回傳 [sentences, remaining] */
function extractSentences(buffer) {
    const sentences = [];
    let remaining = buffer;
    let m;
    while ((m = /^([^。！？]*[。！？])/.exec(remaining)) !== null) {
        const s = m[1].trim();
        if (s.length > 2) sentences.push(s);
        remaining = remaining.slice(m[1].length);
    }
    return [sentences, remaining];
}

/** 播放單個 Blob，resolve 後才繼續下一句 */
function playAudioBlob(blob) {
    return new Promise(resolve => {
        if (!blob) { resolve(); return; }
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
        audio.onerror = () => { URL.revokeObjectURL(url); resolve(); };
        audio.play().catch(resolve);
    });
}

/**
 * 逐句 TTS 佇列
 * push(chunk) → 每收到一段文字就抽句子並立即送 TTS（非同步，不等回應）
 * flush()     → stream 結束後把剩餘碎片也送出
 * playAll()   → 依序播放（fetch 已並行進行，播放時大多已備妥）
 */
class StreamingTTSQueue {
    constructor() {
        this._pending = [];  // Array of Promise<Blob>
        this._buf = "";
    }
    push(chunk) {
        this._buf += chunk;
        const [sentences, remaining] = extractSentences(this._buf);
        this._buf = remaining;
        for (const s of sentences) this._pending.push(fetchTTSBlob(s));
    }
    flush() {
        const s = this._buf.trim();
        if (s.length > 2) this._pending.push(fetchTTSBlob(s));
        this._buf = "";
    }
    async playAll() {
        const portrait = document.getElementById("persona-portrait");
        const ring1    = document.getElementById("speaking-ring-1");
        const ring2    = document.getElementById("speaking-ring-2");
        const lbl      = document.getElementById("status-label");
        const pname    = document.getElementById("persona-portrait-name");
        // 開始說話動畫
        if (portrait) portrait.classList.add("speaking");
        if (ring1) ring1.classList.add("active");
        if (ring2) ring2.classList.add("active");
        if (lbl && pname) { lbl.textContent = `${pname.textContent} 正在回你`; lbl.className = "status-label speaking"; }
        // 依序播放每一句（fetch 已提前並行執行）
        for (const p of this._pending) await playAudioBlob(await p);
        // 結束動畫
        if (portrait) portrait.classList.remove("speaking");
        if (ring1) ring1.classList.remove("active");
        if (ring2) ring2.classList.remove("active");
        if (lbl && pname) { lbl.textContent = "可以慢慢說，我在聽"; lbl.className = "status-label listening"; }
    }
    get isEmpty() { return this._pending.length === 0; }
}

// ── 主對話流程 ──────────────────────────────────────────────────────────────

async function processAndRespond(message, speedEmotion = "normal") {
    // 新訊息送出時清除上一輪的回憶圖片，恢復頭像置中
    const prevFrame = document.getElementById("image-frame");
    if (prevFrame && prevFrame.style.display !== "none") {
        prevFrame.style.display = "none";
        const prevPanel = document.querySelector(".persona-panel");
        if (prevPanel) prevPanel.classList.remove("with-image");
        const prevMain = document.querySelector(".main-body");
        if (prevMain) prevMain.classList.remove("has-image");
        const r1 = document.getElementById("speaking-ring-1");
        const r2 = document.getElementById("speaking-ring-2");
        if (r1) r1.classList.remove("active");
        if (r2) r2.classList.remove("active");
    }

    document.getElementById("text-input").disabled = true;
    document.getElementById("send-btn").disabled = true;
    document.getElementById("hold-talk-btn").disabled = true;

    const thinkingId = addThinking();
    try {
        const ttsQueue = new StreamingTTSQueue();
        const res = await elderFetch("/api/chat?stream=true", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: elderBody({
                message: message,
                speed_emotion: speedEmotion,
                session_id: SESSION_ID,
                persona_id: SELECTED_PERSONA
            })
        });
        if (!res.ok) throw new Error("chat");
        const data = await readChatResponse(res, thinkingId, ttsQueue);
        removeThinking(thinkingId);
        if (!data._streamed) {
            addMessage("ai", data.message);
        }

        if (data.image) {
            if (data.image_caption) {
                addMessage('ai', data.image_caption);
            }
            addImageMessage(data.image);
        }

        if (data.health_info) {
            addHealthCard(data.health_info);
        }
        if (data.background_task_id) {
            pollChatBackground(data.background_task_id);
        }

        if (data.trend_alert) {
            addTrendAlert(data.trend_alert);
        }

        if (data.escalation_level >= 3) {
            addEscalationAlert(3, "🚨 緊急！請立刻通知照護人員！");
        } else if (data.escalation_level >= 2) {
            addEscalationAlert(2, "⚠️ 請通知照護人員關心長者狀況");
        }

        chatCount++;
        document.getElementById("chat-count").textContent = chatCount;

        // 用後端回傳的情緒更新狀態列
        const emotionMap = {
            "urgent": ["🚨", "需要關注"],
            "comfort": ["😢", "需要關懷"],
            "happy": ["😊", "心情愉快"],
            "normal": ["😐", "正常"]
        };
        const [emoji, text] = emotionMap[data.emotion] || ["😐", "正常"];
        updateEmotionStatus(emoji, text);

        // 串流 TTS：queue 已在收 chunk 時提前送出請求，依序播放即可
        ttsQueue.flush();
        if (!ttsQueue.isEmpty) {
            await ttsQueue.playAll();
        } else {
            // fallback：無句尾符號（極短回應）
            await speakText(data.message, data.emotion || "normal");
        }

    } catch (e) {
        removeThinking(thinkingId);
        addMessage("system", "剛剛沒有回好，我們再試一次。");
    } finally {
        document.getElementById("text-input").disabled = false;
        document.getElementById("send-btn").disabled = false;
        document.getElementById("hold-talk-btn").disabled = false;
    }
}

async function readChatResponse(response, thinkingId, ttsQueue = null) {
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("text/event-stream") || !response.body) {
        return response.json();
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let fullText = "";
    let bubble = null;
    let metadata = {};

    const handleEvent = (rawEvent) => {
        const dataLine = rawEvent
            .split(/\r?\n/)
            .find(line => line.startsWith("data:"));
        if (!dataLine) return;
        const event = JSON.parse(dataLine.slice(5).trim());
        if (event.done) {
            metadata = event;
            return;
        }
        const chunk = event.chunk || "";
        if (!chunk) return;
        if (!bubble) {
            removeThinking(thinkingId);
            bubble = addMessage("ai", "");
        }
        fullText += chunk;
        bubble.textContent = fullText;
        const container = document.getElementById("chat-container");
        if (container) container.scrollTop = container.scrollHeight;
        // 逐句提前送 TTS（不等回應，與後續 chunk 並行下載）
        if (ttsQueue) ttsQueue.push(chunk);
    };

    while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const events = buffer.split(/\r?\n\r?\n/);
        buffer = events.pop() || "";
        events.forEach(handleEvent);
        if (done) break;
    }
    if (buffer.trim()) handleEvent(buffer);

    if (!bubble && metadata.message) {
        removeThinking(thinkingId);
        addMessage("ai", metadata.message);
    }
    return {
        ...metadata,
        message: metadata.message || fullText,
        _streamed: true
    };
}

async function pollChatBackground(taskId) {
    let imageShown = false;
    let healthShown = false;
    console.log(`[圖片] 開始輪詢 task=${taskId}`);
    for (let attempt = 0; attempt < 60; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        try {
            const res = await elderFetch(elderQueryPath(`/api/elder/chat/background/${encodeURIComponent(taskId)}`));
            if (!res.ok) return;
            const data = await res.json();
            console.log(`[圖片] attempt=${attempt+1} image_status=${data.image_status} health_status=${data.health_status}`);
            if (!imageShown && data.image_status !== "pending" && data.image) {
                if (data.image_caption) addMessage("ai", data.image_caption);
                addImageMessage(data.image);
                imageShown = true;
                console.log("[圖片] 顯示成功");
            }
            if (!healthShown && data.health_status !== "pending" && data.health_info) {
                addHealthCard(data.health_info);
                healthShown = true;
            }
            if (data.image_status !== "pending" && data.health_status !== "pending") return;
        } catch (e) {
            console.error("背景結果查詢失敗", e);
            return;
        }
    }
    console.log("[圖片] 輪詢超時（60秒）");
}

async function toggleRecording() {
    if (isRecording) {
        stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
            await sendAudioToSTT(audioBlob);
            stream.getTracks().forEach(t => t.stop());
        };

        mediaRecorder.start();
        isRecording = true;

        document.getElementById("hold-talk-btn").classList.add("recording");
        document.getElementById("hold-talk-btn").textContent = "我在聽你說";
        document.getElementById("recording-indicator").classList.add("active");
        document.getElementById("voice-status").textContent = "我在聽你說";

    } catch (e) {
        addMessage("system", "現在聽不到聲音，請確認麥克風可以使用。");
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        document.getElementById("hold-talk-btn").classList.remove("recording");
        document.getElementById("hold-talk-btn").textContent = "開始說話";
        document.getElementById("voice-status").textContent = "我想一下";
    }
}

async function sendAudioToSTT(audioBlob) {
    try {
        const formData = new FormData();
        formData.append("audio", audioBlob, "recording.webm");
        const res = await fetch(`${API_BASE}/api/stt`, {
            method: "POST",
            body: formData
        });
        const data = await res.json();
            document.getElementById("recording-indicator").classList.remove("active");        
            if (data.success && data.text) {
            addMessage("user", data.text);
            await processAndRespond(data.text, data.speed_emotion || "normal");
        } else {
            addMessage("system", "剛剛沒聽清楚，我們再說一次。");
        }
    } catch (e) {
        document.getElementById("recording-indicator").classList.remove("active");
        addMessage("system", "聲音沒有送出去，我們再試一次。");
    }
}

async function speakText(text, emotion = "normal") {
    return new Promise(async (resolve) => {
        try {
            const res = await elderFetch("/api/elder/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: elderBody({
                text: text,
                emotion: emotion,
                persona_id: SELECTED_PERSONA
                })
            });
            const audioBlob = await res.blob();
            const audio = new Audio(URL.createObjectURL(audioBlob));
            audio.onended = resolve;
            audio.onerror = resolve;
            audio.play();
        } catch (e) {
            console.error("TTS 失敗：", e);
            resolve();
        }
    });
}

function addMessage(role, text) {
    const container = document.getElementById("chat-container");
    if (!container) return;
    const placeholder = container.querySelector(".chat-empty");
    if (placeholder) placeholder.remove();

    const row = document.createElement("div");

    if (role === "ai") {
        const avatarSrc = safeAvatarSrc(currentPersonaAvatar, "/static/avatars/ai_assistant_nobg.png");
        row.className = "msg-row";
        const avatar = document.createElement("img");
        avatar.className = "msg-avatar";
        avatar.src = avatarSrc;
        avatar.alt = "陪伴者";
        const bubble = document.createElement("div");
        bubble.className = "msg-bubble ai";
        bubble.textContent = text || "";
        row.append(avatar, bubble);
    } else if (role === "user") {
        const elderAvatar = safeAvatarSrc(currentElderAvatar, "/static/avatars/elder_male.png");
        row.className = "msg-row user";
        const avatar = document.createElement("img");
        avatar.className = "msg-avatar";
        avatar.src = elderAvatar;
        avatar.alt = "長者";
        const bubble = document.createElement("div");
        bubble.className = "msg-bubble user";
        bubble.textContent = text || "";
        row.append(avatar, bubble);
    } else {
        row.style.cssText = "text-align:center;color:#6B5E58;font-size:22px;padding:10px;";
        row.textContent = text;
    }

    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
    return row.querySelector(".msg-bubble") || row;
}

function addThinking() {
    const container = document.getElementById("chat-container");
    if (!container) return "no-container";
    const id = "thinking-" + Date.now();
    const div = document.createElement("div");
    div.id = id;
    div.className = "msg-row";
    div.innerHTML = `
        <div class="msg-avatar ai">…</div>
        <div class="msg-bubble ai" style="padding: 16px 20px;">
            <div style="display:flex; gap:6px; align-items:center;">
                <div style="width:10px;height:10px;background:#D6CEC7;border-radius:50%;animation:bounce 1s infinite;animation-delay:0s"></div>
                <div style="width:10px;height:10px;background:#D6CEC7;border-radius:50%;animation:bounce 1s infinite;animation-delay:0.15s"></div>
                <div style="width:10px;height:10px;background:#D6CEC7;border-radius:50%;animation:bounce 1s infinite;animation-delay:0.3s"></div>
            </div>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function setListeningStatus() {
    const lbl = document.getElementById("status-label");
    if (lbl) {
        lbl.textContent = "可以慢慢說，我在聽";
        lbl.className = "status-label listening";
    }
}

function removeThinking(id) {
    if (id === "no-container") return;
    const el = document.getElementById(id);
    if (el) el.remove();
}

function addImageMessage(imageBase64) {
    const frame = document.getElementById("image-frame");
    const img = document.getElementById("image-frame-img");
    const panel = document.querySelector(".persona-panel");

    img.src = imageBase64;

    // 重設動畫
    frame.style.display = "none";
    frame.style.animation = "none";
    frame.offsetHeight; // reflow
    frame.style.animation = "";
    frame.style.display = "block";

    // 整個 panel（頭像＋名字＋稱位＋狀態）略左移，圖片從右下 overlap
    if (panel) panel.classList.add("with-image");
    const mainBody = document.querySelector(".main-body");
    if (mainBody) mainBody.classList.add("has-image");

    // 圖片出現時重啟呼吸光暈
    const ring1 = document.getElementById("speaking-ring-1");
    const ring2 = document.getElementById("speaking-ring-2");
    if (ring1) { ring1.classList.remove("active"); void ring1.offsetWidth; ring1.classList.add("active"); }
    if (ring2) { ring2.classList.remove("active"); void ring2.offsetWidth; ring2.classList.add("active"); }
}

function addHealthCard(info) {
    const container = document.getElementById("chat-container");
    const wrapper = document.createElement("div");
    wrapper.className = "flex items-start gap-2";
    const icon = document.createElement("div");
    icon.className = "text-2xl";
    icon.textContent = "🌸";
    const card = document.createElement("div");
    card.className = "chat-bubble-ai px-4 py-4 rounded-2xl rounded-tl-none shadow-sm";
    card.style.maxWidth = "360px";
    const label = document.createElement("div");
    label.style.cssText = "font-size:13px;color:#7B9E87;margin-bottom:6px;font-weight:500;";
    label.textContent = "💊 健康衛教資訊";
    const title = document.createElement("div");
    title.style.cssText = "font-size:15px;font-weight:500;color:#3D3530;margin-bottom:6px;";
    title.textContent = info.title || "";
    const summary = document.createElement("div");
    summary.style.cssText = "font-size:13px;color:#7F8C8D;margin-bottom:10px;line-height:1.6;";
    summary.textContent = info.summary || "";
    card.append(label, title, summary);
    const safeUrl = safeHttpUrl(info.url);
    if (safeUrl) {
        const link = document.createElement("a");
        link.href = safeUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.style.cssText = "font-size:13px;color:#4A90E2;text-decoration:none;";
        link.textContent = "📖 查看完整資訊 →";
        card.appendChild(link);
    }
    wrapper.append(icon, card);
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

function addTrendAlert(alertMsg) {
    const container = document.getElementById("chat-container");
    const wrapper = document.createElement("div");
    wrapper.style.cssText = "text-align: center; margin: 8px 0;";
    const alert = document.createElement("div");
    alert.style.cssText = "display:inline-block;background:#FDECEA;border:1px solid #E74C3C;border-radius:10px;padding:8px 16px;font-size:14px;color:#922B21;";
    alert.textContent = alertMsg || "";
    wrapper.appendChild(alert);
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

function updateEmotionStatus(emoji, text) {
    const el = document.getElementById("emotion-display");
    if (el) el.textContent = `${emoji} ${text}`;
}

function clearChat() {
    document.getElementById("chat-container").innerHTML =
        `<div class="chat-empty"><div class="chat-empty-icon">💬</div><div class="chat-empty-text">可以慢慢說<br>我會在這裡陪你</div></div>`;
    chatCount = 0;
    document.getElementById("chat-count").textContent = "0";
    document.getElementById("emotion-display").textContent = "💛 等你說話";
    document.getElementById("text-input").disabled = true;
    document.getElementById("send-btn").disabled = true;
    document.getElementById("hold-talk-btn").disabled = true;
    document.getElementById("start-btn").textContent = "開始聊天";
    document.getElementById("start-btn").disabled = false;
    document.getElementById("image-frame").style.display = "none";
    const panel = document.querySelector(".persona-panel");
    if (panel) panel.classList.remove("with-image");
    const mainBody = document.querySelector(".main-body");
    if (mainBody) mainBody.classList.remove("has-image");
}

try {
    document.getElementById("text-input").addEventListener("keypress", (e) => {
        if (e.key === "Enter") sendMessage();
    });
    const holdBtn = document.getElementById("hold-talk-btn");
    holdBtn.addEventListener("mousedown", startRecording);
    holdBtn.addEventListener("mouseup", stopRecording);
    holdBtn.addEventListener("mouseleave", () => { if (isRecording) stopRecording(); });
    holdBtn.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
    holdBtn.addEventListener("touchend", stopRecording);
    document.getElementById("send-btn").addEventListener("click", sendMessage);
    document.getElementById("start-btn").addEventListener("click", startSession);
    document.getElementById("clear-btn").addEventListener("click", clearChat);
} catch (e) {
    console.error("事件綁定失敗：", e);
}
async function loadWelcomePersonas(elderId) {
    try {
        const res = await elderFetch(elderQueryPath("/api/elder/personas"));
        const data = await res.json();
        const personas = data.personas || {};
        const visiblePersonas = Object.entries(personas).filter(([id]) => id !== 'ai');
        const activeId = visiblePersonas.some(([id]) => id === SELECTED_PERSONA)
            ? SELECTED_PERSONA
            : null;

        const container = document.getElementById('welcome-persona-list');
        container.innerHTML = '';

        const avatarMap = {
            'ai': '/static/avatars/ai_assistant_nobg.png',
            'daughter': '/static/avatars/daughter_bg.png',
            'son': '/static/avatars/son_bg.png',
            'granddaughter': '/static/avatars/granddaughter_bg.png',
            'grandson': '/static/avatars/grandson_bg.png',
        };

        visiblePersonas.forEach(([id, persona]) => {
            const isSelected = id === activeId;
            const avatarSrc = safeAvatarSrc(persona.avatar_path, avatarMap[id] || '/static/avatars/ai_assistant_nobg.png');

            const div = document.createElement('div');
            div.id = `persona-btn-${id}`;
            div.className = `persona-cell${isSelected ? ' selected' : ''}`;
            div.tabIndex = 0;
            div.setAttribute('role', 'button');
            div.setAttribute('aria-label', `和${persona.name || '家人'}說話`);
            const choose = () => {
                selectPersona(id, avatarSrc, persona.name, persona.relation);
                enterChat();
            };
            div.onclick = choose;
            div.onkeydown = (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    choose();
                }
            };
            const avatar = document.createElement('img');
            avatar.className = 'persona-cell-avatar';
            avatar.src = avatarSrc;
            avatar.alt = persona.name || '陪伴者';
            const name = document.createElement('div');
            name.className = 'persona-cell-name';
            name.textContent = persona.name || '陪伴者';
            div.append(avatar, name);
            if (persona.relation) {
                const relation = document.createElement('div');
                relation.className = 'persona-cell-rel';
                relation.textContent = persona.relation;
                div.appendChild(relation);
            }
            container.appendChild(div);
            if (isSelected) {
                selectPersona(id, avatarSrc, persona.name, persona.relation);
            }
        });
    } catch (e) {
        console.error('載入人格失敗', e);
    }
}

function addEscalationAlert(level, message) {
    const container = document.getElementById("chat-container");
    const wrapper = document.createElement("div");
    const bgColor = level >= 3 ? "#FDECEA" : "#FEF3CD";
    const borderColor = level >= 3 ? "#E74C3C" : "#F39C12";
    const textColor = level >= 3 ? "#922B21" : "#7D5A00";
    const fontSize = level >= 3 ? "20px" : "17px";
    wrapper.style.cssText = "text-align: center; margin: 8px 0;";
    const alert = document.createElement("div");
    alert.style.cssText = `display:inline-block;background:${bgColor};border:2px solid ${borderColor};border-radius:12px;padding:12px 24px;font-size:${fontSize};color:${textColor};font-weight:700;`;
    alert.textContent = message || "";
    wrapper.appendChild(alert);
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

async function prepareActivePersona(elderId) {
    try {
        const res = await elderFetch(elderQueryPath("/api/elder/personas"));
        const data = await res.json();
        const personas = data.personas || {};
        const visiblePersonas = Object.entries(personas).filter(([id]) => id !== 'ai');
        const activeId = urlParams.get("persona") || SELECTED_PERSONA || data.active_persona || visiblePersonas[0]?.[0] || "ai";
        const persona = personas[activeId] || visiblePersonas[0]?.[1] || Object.values(personas)[0] || {};
        const personaId = personas[activeId] ? activeId : (visiblePersonas[0]?.[0] || Object.keys(personas)[0] || "ai");

        const avatarMap = {
            'ai': '/static/avatars/ai_assistant_nobg.png',
            'daughter': '/static/avatars/daughter.png',
            'son': '/static/avatars/son.png',
            'granddaughter': '/static/avatars/granddaughter.png',
            'grandson': '/static/avatars/grandson.png',
        };

        SELECTED_PERSONA = personaId;
        currentPersonaAvatar = safeAvatarSrc(persona.avatar_path, avatarMap[personaId] || '/static/avatars/ai_assistant_nobg.png');

        const portrait = document.getElementById('persona-portrait');
        const nameDisplay = document.getElementById('persona-portrait-name');
        const relDisplay = document.getElementById('persona-portrait-rel');
        if (portrait) portrait.src = currentPersonaAvatar;
        if (nameDisplay) nameDisplay.textContent = persona.name || '陪伴者';
        if (relDisplay) relDisplay.textContent = persona.relation || '陪你說說話';
    } catch (e) {
        console.error('準備陪伴者失敗', e);
    }
}

function selectPersona(personaId, avatarSrc, name, relation) {
    SELECTED_PERSONA = personaId;
    currentPersonaAvatar = avatarSrc;

    document.querySelectorAll('.persona-cell').forEach(btn => {
        btn.classList.remove('selected');
        const check = btn.querySelector('.persona-cell-check');
        if (check) check.remove();
    });

    const selected = document.getElementById(`persona-btn-${personaId}`);
    if (selected) {
        selected.classList.add('selected');
        const check = document.createElement('div');
        check.className = 'persona-cell-check';
        selected.appendChild(check);
    }

    const welcomeBubble = document.getElementById('welcome-active-bubble');
    if (welcomeBubble) {
        welcomeBubble.innerHTML = '家人和我都在這裡陪你喔<br>想和我，還是哪位家人說說話？';
    }
}

async function speakText(text, emotion = "normal") {
    return new Promise(async (resolve) => {
        try {
            // 開始說話：加光暈
            const portrait = document.getElementById("persona-portrait");
            const ring1 = document.getElementById("speaking-ring-1");
            const ring2 = document.getElementById("speaking-ring-2");
            if (portrait) portrait.classList.add("speaking");
            if (ring1) ring1.classList.add("active");
            if (ring2) ring2.classList.add("active");
            const lbl = document.getElementById("status-label");
            const pname = document.getElementById("persona-portrait-name");
            if (lbl && pname) {
                lbl.textContent = `${pname.textContent} 正在回你`;
                lbl.className = "status-label speaking";
            }

            const res = await elderFetch("/api/elder/tts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: elderBody({
                    text,
                    emotion,
                    persona_id: SELECTED_PERSONA
                })
            });
            const audioBlob = await res.blob();
            const audio = new Audio(URL.createObjectURL(audioBlob));
            const resetSpeaking = () => {
                if (portrait) portrait.classList.remove("speaking");
                if (ring1) ring1.classList.remove("active");
                if (ring2) ring2.classList.remove("active");
                const lbl = document.getElementById("status-label");
                const pname = document.getElementById("persona-portrait-name");
                if (lbl && pname) {
                    lbl.textContent = "可以慢慢說，我在聽";
                    lbl.className = "status-label listening";
                }
            };
            audio.onended = () => { resetSpeaking(); resolve(); };
            audio.onerror = () => { resetSpeaking(); resolve(); };
            audio.play();
        } catch (e) {
            console.error("TTS 失敗：", e);
            resolve();
        }
    });
}

async function enterChat() {
    document.getElementById('welcome-screen').style.display = 'none';
    document.getElementById('main-screen').style.display = 'flex';

    await prepareActivePersona(ELDER_ID);

    try {
        const res = await elderFetch(elderQueryPath("/api/elder/profile"));
        const profile = await res.json();
        const nameEl = document.getElementById("elder-name-display");
        if (nameEl) nameEl.textContent = profile.name || "未知";

        currentElderAvatar = profile.gender === 'female'
            ? '/static/avatars/elder_female.png'
            : '/static/avatars/elder_male.png';

    } catch (e) {
        console.error('載入長者資料失敗', e);
    }

    // 自動開始對話
    await startSession();
    startVAD();
}

async function showPersonaSwitcher() {
    try {
        const res = await elderFetch(elderQueryPath("/api/elder/personas"));
        const data = await res.json();
        const personas = data.personas || {};
        const activeId = SELECTED_PERSONA || data.active_persona || 'ai';

        const avatarMap = {
            'ai': '/static/avatars/ai_assistant_nobg.png',
            'daughter': '/static/avatars/daughter.png',
            'son': '/static/avatars/son.png',
            'granddaughter': '/static/avatars/granddaughter.png',
            'grandson': '/static/avatars/grandson.png',
        };

        const container = document.getElementById('switcher-persona-list');
        container.innerHTML = '';

        Object.entries(personas).forEach(([id, persona]) => {
            const isActive = id === activeId;
            const avatarSrc = safeAvatarSrc(persona.avatar_path, avatarMap[id] || '/static/avatars/ai_assistant_nobg.png');

            const div = document.createElement('div');
            div.className = `switcher-persona-option${isActive ? ' active' : ''}`;
            div.tabIndex = 0;
            div.setAttribute('role', 'button');
            div.setAttribute('aria-label', `換成${persona.name || '陪伴者'}陪你說話`);
            const avatar = document.createElement('img');
            avatar.src = avatarSrc;
            avatar.alt = persona.name || '陪伴者';
            const textWrap = document.createElement('div');
            const name = document.createElement('div');
            name.style.cssText = "font-size:24px;font-weight:700;color:var(--text-dark);";
            name.textContent = persona.name || '陪伴者';
            const relation = document.createElement('div');
            relation.style.cssText = "font-size:18px;color:var(--text-mid);margin-top:4px;";
            relation.textContent = persona.relation || '陪你說說話';
            textWrap.append(name, relation);
            div.append(avatar, textWrap);
            if (isActive) {
                const active = document.createElement('div');
                active.style.cssText = "margin-left:auto;color:var(--orange);font-size:20px;font-weight:700;";
                active.textContent = "正在陪你";
                div.appendChild(active);
            }
            if (!isActive) {
                const choose = () => switchPersonaInChat(id, avatarSrc, persona.name, persona.relation);
                div.onclick = choose;
                div.onkeydown = (event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        choose();
                    }
                };
            }
            container.appendChild(div);
        });

        document.getElementById('persona-switcher').style.display = 'flex';
    } catch (e) {
        console.error('載入人格失敗', e);
    }
}

async function switchPersonaInChat(personaId, avatarSrc, name, relation) {
    try {
        SELECTED_PERSONA = personaId;
        // 更新右側頭像
        currentPersonaAvatar = avatarSrc;
        document.getElementById('persona-portrait').src = avatarSrc;
        document.getElementById('persona-portrait-name').textContent = name;
        document.getElementById('persona-portrait-rel').textContent = relation || '陪你說說話';

        closeSwitcher();

        // 清除對話重新開始
        clearChat();
        addMessage('system', `已換成 ${name || '陪伴者'}，可以繼續說話。`);
        await startSession();

    } catch (e) {
        console.error('切換失敗', e);
    }
}

function closeSwitcher() {
    document.getElementById('persona-switcher').style.display = 'none';
}

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        closeSwitcher();
    }
});

async function startAuthenticatedView() {
    await loadElderProfile();
    const elderSwitchSelect = document.getElementById("elder-switch-select");
    if (elderSwitchSelect) elderSwitchSelect.value = ELDER_ID;
    if (urlParams.get("autostart") === "1") {
        await enterChat();
        return;
    }
    document.getElementById('welcome-screen').style.display = 'flex';
    document.getElementById('main-screen').style.display = 'none';
    await loadWelcomePersonas(ELDER_ID);
}

async function loadDemoControls() {
    const controls = document.querySelector(".demo-controls");
    if (controls) controls.style.display = "flex";
    try {
        const res = await fetch(`${API_BASE}/api/admin/elders`);
        if (!res.ok) return;
        const data = await res.json();
        const select = document.getElementById("elder-switch-select");
        if (!select) return;
        select.innerHTML = "";
        for (const elder of data.elders || []) {
            const option = document.createElement("option");
            option.value = elder.elder_id;
            option.textContent = `${elder.name}（${elder.elder_id}）`;
            select.appendChild(option);
        }
        select.value = ELDER_ID;
    } catch (e) {
        console.error("載入 Demo 長者清單失敗", e);
    }
}

async function initializeApp() {
    if (!ELDER_ID) {
        const urlElderId = urlParams.get("elder");
        if (urlElderId) {
            ELDER_ID = urlElderId;
            sessionStorage.setItem("care4u_elder_id", ELDER_ID);
        }
    }

    try {
        const modeRes = await fetch(`${API_BASE}/api/system/mode`);
        const mode = await modeRes.json();
        if (mode.demo_mode) await loadDemoControls();
    } catch (e) {
        console.error("載入系統模式失敗", e);
    }

    if (!ELDER_ID) {
        showLaunchHint();
        return;
    }

    try {
        const res = await elderFetch(elderQueryPath("/api/elder/profile"));
        if (!res.ok) throw new Error("invalid token");
        await startAuthenticatedView();
    } catch {
        sessionStorage.removeItem("care4u_elder_id");
        ELDER_ID = "";
        showLaunchHint();
    }
}

initializeApp();

async function startGuideChat() {
    SELECTED_PERSONA = "ai";
    currentPersonaAvatar = "/static/avatars/ai_assistant_nobg.png";
    await enterChat();
}

let vadActive = false;
let vadRecording = false;
let vadStream = null;
let vadAnalyser = null;
let vadRecorder = null;
let vadChunks = [];
let silenceTimer = null;

async function startVAD() {
    if (vadActive) return;
    vadActive = true;

    try {
        vadStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const audioCtx = new AudioContext();
        const source = audioCtx.createMediaStreamSource(vadStream);
        vadAnalyser = audioCtx.createAnalyser();
        vadAnalyser.fftSize = 512;
        source.connect(vadAnalyser);

        const data = new Uint8Array(vadAnalyser.frequencyBinCount);

        function checkVolume() {
            if (!vadActive) return;
            vadAnalyser.getByteFrequencyData(data);
            const volume = data.reduce((a, b) => a + b) / data.length;

            if (volume > 15 && !vadRecording) {
                // 偵測到說話，開始錄音
                vadChunks = [];
                vadRecorder = new MediaRecorder(vadStream);
                vadRecorder.ondataavailable = e => vadChunks.push(e.data);
                vadRecorder.onstop = async () => {
                    const blob = new Blob(vadChunks, { type: 'audio/webm' });
                    await sendAudioToSTT(blob);
                };
                vadRecorder.start();
                vadRecording = true;

                const lbl = document.getElementById('status-label');
                const pname = document.getElementById('persona-portrait-name');
                if (lbl && pname) {
                    lbl.textContent = '可以慢慢說，我在聽';
                    lbl.className = 'status-label listening';
                }
                document.getElementById('recording-indicator')?.classList.add('active');

            } else if (volume <= 15 && vadRecording) {
                // 音量下降，開始計時靜音
                if (!silenceTimer) {
                    silenceTimer = setTimeout(() => {
                        vadRecorder?.stop();
                        vadRecording = false;
                        silenceTimer = null;
                        document.getElementById('recording-indicator')?.classList.remove('active');
                    }, 1500); // 靜音 1.5 秒後送出
                }
            } else if (volume > 25 && vadRecording && silenceTimer) {
                // 靜音中又有聲音，取消靜音計時
                clearTimeout(silenceTimer);
                silenceTimer = null;
            }

            requestAnimationFrame(checkVolume);
        }

        checkVolume();
    } catch (e) {
        console.error('VAD 啟動失敗：', e);
    }
}

function stopVAD() {
    vadActive = false;
    vadStream?.getTracks().forEach(t => t.stop());
}
