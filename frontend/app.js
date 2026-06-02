const urlParams = new URLSearchParams(window.location.search);
let ELDER_ID = urlParams.get("elder") || "W001";
let SELECTED_PERSONA = urlParams.get("persona") || null;
const API_BASE = "http://127.0.0.1:8000";
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
        const res = await fetch(`${API_BASE}/api/profile/${ELDER_ID}`);
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
    ELDER_ID = elderId;
    clearChat();
    await loadElderProfile();
}

async function startSession() {
    const btn = document.getElementById("start-btn");
    btn.textContent = "準備中...";
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/greet`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                elder_id: ELDER_ID,
                session_id: SESSION_ID,
                persona_id: SELECTED_PERSONA
            })
        });
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

async function processAndRespond(message, speedEmotion = "normal") {
    document.getElementById("text-input").disabled = true;
    document.getElementById("send-btn").disabled = true;
    document.getElementById("hold-talk-btn").disabled = true;

    const thinkingId = addThinking();
    try {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                elder_id: ELDER_ID,
                message: message,
                speed_emotion: speedEmotion,
                session_id: SESSION_ID,
                persona_id: SELECTED_PERSONA
            })
        });
        const data = await res.json();
        removeThinking(thinkingId);
        addMessage("ai", data.message);

        if (data.image) {
            if (data.image_caption) {
                addMessage('ai', data.image_caption);
            }
            addImageMessage(data.image);
        }

        if (data.health_info) {
            addHealthCard(data.health_info);
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

        await speakText(data.message, data.emotion || "normal");

    } catch (e) {
        removeThinking(thinkingId);
        addMessage("system", "剛剛沒有回好，我們再試一次。");
    } finally {
        document.getElementById("text-input").disabled = false;
        document.getElementById("send-btn").disabled = false;
        document.getElementById("hold-talk-btn").disabled = false;
    }
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
            const res = await fetch(`${API_BASE}/api/tts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    text: text,
                    emotion: emotion,
                    elder_id: ELDER_ID,
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
    const wrap = document.querySelector(".speaking-wrap");
    const info = document.querySelector(".persona-info");
    const statusLbl = document.getElementById("status-label");

    img.src = imageBase64;

    // 重設動畫
    frame.style.display = "none";
    frame.style.animation = "none";
    frame.offsetHeight; // reflow
    frame.style.animation = "";
    frame.style.display = "block";

    // 人像滑左
    wrap.classList.add("with-image");
    if (info) info.style.display = "none";
    if (statusLbl) statusLbl.style.display = "none";
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
    const wrap = document.querySelector(".speaking-wrap");
    if (wrap) wrap.classList.remove("with-image");
    const info = document.querySelector(".persona-info");
    if (info) info.style.display = "";
    const statusLbl = document.getElementById("status-label");
    if (statusLbl) statusLbl.style.display = "";
}

try {
    loadElderProfile();
} catch (e) {
    console.error("loadElderProfile 失敗：", e);
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
        const res = await fetch(`${API_BASE}/api/profile/${elderId}/personas`);
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
            div.onclick = () => {
                selectPersona(id, avatarSrc, persona.name, persona.relation);
                enterChat();
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
        const res = await fetch(`${API_BASE}/api/profile/${elderId}/personas`);
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

            const res = await fetch(`${API_BASE}/api/tts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    text,
                    emotion,
                    elder_id: ELDER_ID,
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
    ELDER_ID = urlParams.get("elder") || ELDER_ID || "W001";

    document.getElementById('welcome-screen').style.display = 'none';
    document.getElementById('main-screen').style.display = 'flex';

    await prepareActivePersona(ELDER_ID);

    try {
        const res = await fetch(`${API_BASE}/api/profile/${ELDER_ID}`);
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
        const res = await fetch(`${API_BASE}/api/profile/${ELDER_ID}/personas`);
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
if (urlParams.get("autostart") === "1") {
    enterChat();
} else {
    document.getElementById('welcome-screen').style.display = 'flex';
    document.getElementById('main-screen').style.display = 'none';
    loadWelcomePersonas(ELDER_ID);
}

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
