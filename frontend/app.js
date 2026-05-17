const urlParams = new URLSearchParams(window.location.search);
let ELDER_ID = urlParams.get("elder") || null;
let SELECTED_PERSONA = "ai";
const API_BASE = "http://127.0.0.1:8000";

let chatCount = 0;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let currentPersonaAvatar = "/static/avatars/ai_assistant.png";
let currentElderAvatar = "/static/avatars/elder_male.png";

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
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
    btn.textContent = "⏳ 啟動中...";
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/greet`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ elder_id: ELDER_ID })
        });
        const data = await res.json();

        addMessage("ai", data.message);
        enableButtons();
        document.getElementById("text-input").focus();
        btn.textContent = "✅ 對話進行中";
        updateEmotionStatus("😊", "正常");
        await speakText(data.message, "normal");

    } catch (e) {
        btn.textContent = "❌ 啟動失敗，請重試";
        btn.disabled = false;
        addMessage("system", "系統啟動失敗。");
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
                speed_emotion: speedEmotion
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
        addMessage("system", "回應失敗。");
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
        document.getElementById("hold-talk-btn").textContent = "🔴 錄音中...";
        document.getElementById("recording-indicator").classList.add("active");
        document.getElementById("voice-status").textContent = "正在錄音...";

    } catch (e) {
        addMessage("system", "無法存取麥克風，請確認瀏覽器權限。");
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        document.getElementById("hold-talk-btn").classList.remove("recording");
        document.getElementById("hold-talk-btn").textContent = "🎙️ 按住說話";
        document.getElementById("voice-status").textContent = "辨識中...";
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
            document.getElementById("recording-indicator").classList.remove("active");        if (data.success && data.text) {
            addMessage("user", data.text);
            await processAndRespond(data.text, data.speed_emotion || "normal");
        } else {
            addMessage("system", "語音辨識失敗，請再試一次。");
        }
    } catch (e) {
        document.getElementById("recording-indicator").classList.remove("active");
        addMessage("system", "語音傳送失敗。");
    }
}

async function speakText(text, emotion = "normal") {
    return new Promise(async (resolve) => {
        try {
            const res = await fetch(`${API_BASE}/api/tts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text, emotion: emotion })
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
    const placeholder = container.querySelector(".chat-empty");
    if (placeholder) placeholder.remove();

    const row = document.createElement("div");

    if (role === "ai") {
        const avatarSrc = currentPersonaAvatar || "/static/avatars/ai_assistant.png";
        row.className = "msg-row";
        row.innerHTML = `
            <img class="msg-avatar" src="${avatarSrc}" alt="AI">
            <div class="msg-bubble ai">${escapeHtml(text)}</div>
        `;
    } else if (role === "user") {
        const elderAvatar = currentElderAvatar || "/static/avatars/elder_male.png";
        row.className = "msg-row user";
        row.innerHTML = `
            <img class="msg-avatar" src="${elderAvatar}" alt="長者">
            <div class="msg-bubble user">${escapeHtml(text)}</div>
        `;
    } else {
        row.style.cssText = "text-align:center;color:#BDC3C7;font-size:16px;padding:8px;";
        row.textContent = text;
    }

    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
}

function addThinking() {
    const container = document.getElementById("chat-container");
    const id = "thinking-" + Date.now();
    const div = document.createElement("div");
    div.id = id;
    div.className = "msg-row";
    div.innerHTML = `
        <div class="msg-avatar ai">🌸</div>
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

function removeThinking(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function addImageMessage(imageBase64) {
    const frame = document.getElementById("image-frame");
    const img = document.getElementById("image-frame-img");
    frame.style.display = "block";
    img.src = imageBase64;
    img.onclick = () => window.open(imageBase64, '_blank');
}

function addHealthCard(info) {
    const container = document.getElementById("chat-container");
    const wrapper = document.createElement("div");
    wrapper.className = "flex items-start gap-2";
    wrapper.innerHTML = `
        <div class="text-2xl">🌸</div>
        <div class="chat-bubble-ai px-4 py-4 rounded-2xl rounded-tl-none shadow-sm" style="max-width: 360px;">
            <div style="font-size: 13px; color: #7B9E87; margin-bottom: 6px; font-weight: 500;">
                💊 健康衛教資訊
            </div>
            <div style="font-size: 15px; font-weight: 500; color: #3D3530; margin-bottom: 6px;">
                ${escapeHtml(info.title)}
            </div>
            <div style="font-size: 13px; color: #7F8C8D; margin-bottom: 10px; line-height: 1.6;">
                ${escapeHtml(info.summary)}
            </div>
            <a href="${escapeHtml(info.url)}" target="_blank"
               style="font-size: 13px; color: #4A90E2; text-decoration: none;">
                📖 查看完整資訊 →
            </a>
        </div>
    `;
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

function addTrendAlert(alertMsg) {
    const container = document.getElementById("chat-container");
    const wrapper = document.createElement("div");
    wrapper.style.cssText = "text-align: center; margin: 8px 0;";
    wrapper.innerHTML = `
        <div style="display: inline-block; background: #FDECEA; border: 1px solid #E74C3C; border-radius: 10px; padding: 8px 16px; font-size: 14px; color: #922B21;">
            ${escapeHtml(alertMsg)}
        </div>
    `;
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

function updateEmotionStatus(emoji, text) {
    const el = document.getElementById("emotion-display");
    if (el) el.textContent = `${emoji} ${text}`;
}

function clearChat() {
    document.getElementById("chat-container").innerHTML =
        `<div class="chat-empty"><div class="chat-empty-icon">💬</div><div class="chat-empty-text">請點擊下方「開始對話」<br>來啟動陪伴系統</div></div>`;
    chatCount = 0;
    document.getElementById("chat-count").textContent = "0";
    document.getElementById("emotion-display").textContent = "💛 等待對話...";
    document.getElementById("text-input").disabled = true;
    document.getElementById("send-btn").disabled = true;
    document.getElementById("hold-talk-btn").disabled = true;
    document.getElementById("start-btn").textContent = "🌟 開始對話";
    document.getElementById("start-btn").disabled = false;
    document.getElementById("image-frame").style.display = "none";
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
        const activeId = data.active_persona || 'ai';

        const container = document.getElementById('welcome-persona-list');
        container.innerHTML = '';

        const avatarMap = {
            'ai': '/static/avatars/ai_assistant.png',
            'daughter': '/static/avatars/daughter.png',
            'son': '/static/avatars/son.png',
            'granddaughter': '/static/avatars/granddaughter.png',
            'grandson': '/static/avatars/grandson.png',
        };

        Object.entries(personas).forEach(([id, persona]) => {
            const isSelected = id === activeId;
            const avatarSrc = persona.avatar_path
                ? `/static/avatars/${persona.avatar_path}`
                : (avatarMap[id] || '/static/avatars/ai_assistant.png');

            const div = document.createElement('div');
            div.id = `persona-btn-${id}`;
            div.className = `persona-option${isSelected ? ' selected' : ''}`;
            div.onclick = () => selectPersona(id, avatarSrc, persona.name, persona.relation);
            div.innerHTML = `
                <img class="persona-avatar" src="${avatarSrc}" alt="${persona.name}">
                <div class="persona-name">${persona.name}</div>
                <div class="persona-rel">${persona.relation || 'AI 陪伴助理'}</div>
                ${isSelected ? '<div class="persona-check">✓</div>' : ''}
            `;
            container.appendChild(div);

            if (isSelected) {
                SELECTED_PERSONA = id;
                currentPersonaAvatar = avatarSrc;
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
    wrapper.innerHTML = `
        <div style="display:inline-block; background:${bgColor};
             border: 2px solid ${borderColor}; border-radius: 12px;
             padding: 12px 24px; font-size:${fontSize};
             color:${textColor}; font-weight:700;">
            ${escapeHtml(message)}
        </div>
    `;
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

function selectPersona(personaId, avatarSrc, name, relation) {
    SELECTED_PERSONA = personaId;
    currentPersonaAvatar = avatarSrc;

    document.querySelectorAll('.persona-option').forEach(btn => {
        btn.classList.remove('selected');
        const check = btn.querySelector('.persona-check');
        if (check) check.remove();
    });

    const selected = document.getElementById(`persona-btn-${personaId}`);
    if (selected) {
        selected.classList.add('selected');
        const check = document.createElement('div');
        check.className = 'persona-check';
        check.textContent = '✓';
        selected.appendChild(check);
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

            const res = await fetch(`${API_BASE}/api/tts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text, emotion })
            });
            const audioBlob = await res.blob();
            const audio = new Audio(URL.createObjectURL(audioBlob));
            audio.onended = () => {
                // 停止說話：移除光暈
                if (portrait) portrait.classList.remove("speaking");
                if (ring1) ring1.classList.remove("active");
                if (ring2) ring2.classList.remove("active");
                resolve();
            };
            audio.onerror = () => {
                if (portrait) portrait.classList.remove("speaking");
                if (ring1) ring1.classList.remove("active");
                if (ring2) ring2.classList.remove("active");
                resolve();
            };
            audio.play();
        } catch (e) {
            console.error("TTS 失敗：", e);
            resolve();
        }
    });
}

async function enterChat() {
    ELDER_ID = document.getElementById('welcome-elder-select').value;

    try {
        await fetch(`${API_BASE}/api/profile/persona/switch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ elder_id: ELDER_ID, persona_id: SELECTED_PERSONA })
        });
    } catch (e) {
        console.error('切換人格失敗', e);
    }

    document.getElementById('welcome-screen').style.display = 'none';
    document.getElementById('main-screen').style.display = 'flex';

    // 更新右側頭像
    const portrait = document.getElementById('persona-portrait');
    if (portrait) portrait.src = currentPersonaAvatar;

    // 根據性別設定長者頭像
    try {
        const res = await fetch(`${API_BASE}/api/profile/${ELDER_ID}`);
        const profile = await res.json();
        const nameEl = document.getElementById("elder-name-display");
        if (nameEl) nameEl.textContent = profile.name || "未知";

        currentElderAvatar = profile.gender === 'female'
            ? '/static/avatars/elder_female.png'
            : '/static/avatars/elder_male.png';

        // 更新右側人格名稱
        const personas = profile.personas || {};
        const activePersona = personas[SELECTED_PERSONA] || {};
        const nameDisplay = document.getElementById('persona-portrait-name');
        const relDisplay = document.getElementById('persona-portrait-rel');
        if (nameDisplay) nameDisplay.textContent = activePersona.name || 'AI 助理';
        if (relDisplay) relDisplay.textContent = activePersona.relation || '您的智慧照護陪伴';
    } catch (e) {
        console.error('載入長者資料失敗', e);
    }
}
async function showPersonaSwitcher() {
    try {
        const res = await fetch(`${API_BASE}/api/profile/${ELDER_ID}/personas`);
        const data = await res.json();
        const personas = data.personas || {};
        const activeId = data.active_persona || 'ai';

        const avatarMap = {
            'ai': '/static/avatars/ai_assistant.png',
            'daughter': '/static/avatars/daughter.png',
            'son': '/static/avatars/son.png',
            'granddaughter': '/static/avatars/granddaughter.png',
            'grandson': '/static/avatars/grandson.png',
        };

        const container = document.getElementById('switcher-persona-list');
        container.innerHTML = '';

        Object.entries(personas).forEach(([id, persona]) => {
            const isActive = id === activeId;
            const avatarSrc = persona.avatar_path
                ? `/static/avatars/${persona.avatar_path}`
                : (avatarMap[id] || '/static/avatars/ai_assistant.png');

            const div = document.createElement('div');
            div.style.cssText = `
                display: flex; align-items: center; gap: 16px; padding: 14px 18px;
                border-radius: 14px; cursor: pointer;
                border: 2px solid ${isActive ? 'var(--orange)' : 'var(--border)'};
                background: ${isActive ? '#FEF3E8' : 'white'};
                transition: all 0.2s;
            `;
            div.innerHTML = `
                <img src="${avatarSrc}" style="width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid var(--border);">
                <div>
                    <div style="font-size:20px;font-weight:700;color:var(--text-dark);">${persona.name}</div>
                    <div style="font-size:14px;color:var(--text-light);">${persona.relation || 'AI 陪伴助理'}</div>
                </div>
                ${isActive ? '<div style="margin-left:auto;color:var(--orange);font-size:20px;">✓ 使用中</div>' : ''}
            `;
            if (!isActive) {
                div.onclick = () => switchPersonaInChat(id, avatarSrc, persona.name, persona.relation);
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
        await fetch(`${API_BASE}/api/profile/persona/switch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ elder_id: ELDER_ID, persona_id: personaId })
        });

        // 更新右側頭像
        currentPersonaAvatar = avatarSrc;
        document.getElementById('persona-portrait').src = avatarSrc;
        document.getElementById('persona-portrait-name').textContent = name;
        document.getElementById('persona-portrait-rel').textContent = relation || 'AI 陪伴助理';

        closeSwitcher();

        // 清除對話重新開始
        clearChat();
        addMessage('system', `已切換到 ${name}，請重新開始對話`);

    } catch (e) {
        console.error('切換失敗', e);
    }
}

function closeSwitcher() {
    document.getElementById('persona-switcher').style.display = 'none';
}
if (ELDER_ID) {
    document.getElementById('welcome-screen').style.display = 'none';
    document.getElementById('main-screen').style.display = 'flex';
    loadElderProfile();
} else {
    loadWelcomePersonas('W001');
}