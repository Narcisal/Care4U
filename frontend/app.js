const ELDER_ID = "W001";
const API_BASE = "http://127.0.0.1:8000";

let chatCount = 0;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

function enableButtons() {
    document.getElementById("text-input").removeAttribute("disabled");
    document.getElementById("send-btn").removeAttribute("disabled");
    document.getElementById("record-btn").removeAttribute("disabled");
}

async function loadElderProfile() {
    try {
        const res = await fetch(`${API_BASE}/api/profile/${ELDER_ID}`);
        const profile = await res.json();
        document.getElementById("elder-name").textContent = profile.name || "未知";
    } catch (e) {
        document.getElementById("elder-name").textContent = "載入失敗";
    }
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
        speakText(data.message);

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
    await processAndRespond(message);
}

async function processAndRespond(message) {
    // 鎖住輸入，避免 AI 還沒回應前繼續輸入
    document.getElementById("text-input").disabled = true;
    document.getElementById("send-btn").disabled = true;
    document.getElementById("record-btn").disabled = true;

    const thinkingId = addThinking();
    try {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ elder_id: ELDER_ID, message: message })
        });
        const data = await res.json();
        removeThinking(thinkingId);
        addMessage("ai", data.message);
        chatCount++;
        document.getElementById("chat-count").textContent = chatCount;
        updateEmotionFromMessage(message);

        // 等 TTS 播完再解鎖
        await speakText(data.message, data.emotion || "normal");

    } catch (e) {
        removeThinking(thinkingId);
        addMessage("system", "回應失敗。");
    } finally {
        // 不管成功或失敗都解鎖
        document.getElementById("text-input").disabled = false;
        document.getElementById("send-btn").disabled = false;
        document.getElementById("record-btn").disabled = false;
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

        const btn = document.getElementById("record-btn");
        btn.textContent = "⏹️ 停止錄音";
        btn.classList.replace("bg-green-500", "bg-red-500");
        btn.classList.replace("hover:bg-green-600", "hover:bg-red-600");
        document.getElementById("voice-visualizer").classList.remove("hidden");
        document.getElementById("voice-status").textContent = "正在錄音...";

    } catch (e) {
        addMessage("system", "無法存取麥克風，請確認瀏覽器權限。");
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        const btn = document.getElementById("record-btn");
        btn.textContent = "🎙️ 語音輸入";
        btn.classList.replace("bg-red-500", "bg-green-500");
        btn.classList.replace("hover:bg-red-600", "hover:bg-green-600");
        document.getElementById("voice-status").textContent = "辨識中...";
    }
}

async function sendAudioToSTT(audioBlob) {
    try {
        const formData = new FormData();
        formData.append("audio", audioBlob, "recording.webm");
        const res = await fetch(`${API_BASE}/api/stt`, { method: "POST", body: formData });
        const data = await res.json();
        document.getElementById("voice-visualizer").classList.add("hidden");
        if (data.success && data.text) {
            addMessage("user", data.text);
            await processAndRespond(data.text);
        } else {
            addMessage("system", "語音辨識失敗，請再試一次。");
        }
    } catch (e) {
        document.getElementById("voice-visualizer").classList.add("hidden");
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
            audio.onended = resolve;      // 播完才 resolve
            audio.onerror = resolve;      // 出錯也 resolve，不卡住
            audio.play();
        } catch (e) {
            console.error("TTS 失敗：", e);
            resolve();                    // 失敗也 resolve，不卡住
        }
    });
}

function addMessage(role, text) {
    const container = document.getElementById("chat-container");
    const placeholder = container.querySelector(".text-center");
    if (placeholder) placeholder.remove();
    const wrapper = document.createElement("div");
    if (role === "ai") {
        wrapper.className = "flex items-start gap-2";
        wrapper.innerHTML = `
            <div class="text-2xl">🌸</div>
            <div class="chat-bubble-ai px-5 py-4 rounded-2xl rounded-tl-none max-w-xs lg:max-w-md shadow-sm">
                <p class="text-lg leading-relaxed">${text}</p>
            </div>`;
    } else if (role === "user") {
        wrapper.className = "flex items-start gap-2 justify-end";
        wrapper.innerHTML = `
            <div class="chat-bubble-user px-5 py-4 rounded-2xl rounded-tr-none max-w-xs lg:max-w-md shadow-sm">
                <p class="text-lg leading-relaxed">${text}</p>
            </div>
            <div class="text-2xl">👴</div>`;
    } else {
        wrapper.className = "text-center text-gray-400 text-sm";
        wrapper.textContent = text;
    }
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

function addThinking() {
    const container = document.getElementById("chat-container");
    const id = "thinking-" + Date.now();
    const div = document.createElement("div");
    div.id = id;
    div.className = "flex items-start gap-2";
    div.innerHTML = `
        <div class="text-2xl">🤖</div>
        <div class="bg-gray-100 px-4 py-3 rounded-2xl rounded-tl-none shadow">
            <div class="flex gap-1 items-center">
                <div class="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style="animation-delay:0s"></div>
                <div class="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style="animation-delay:0.15s"></div>
                <div class="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style="animation-delay:0.3s"></div>
            </div>
        </div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeThinking(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function updateEmotionFromMessage(message) {
    const negative = ["痛", "不舒服", "難過", "孤單", "無聊", "累", "不高興", "煩", "憂鬱", "想哭"];
    const positive = ["開心", "高興", "快樂", "好", "棒", "謝謝", "喜歡", "愛"];
    if (negative.some(kw => message.includes(kw))) {
        updateEmotionStatus("😢", "需要關懷");
    } else if (positive.some(kw => message.includes(kw))) {
        updateEmotionStatus("😊", "心情愉快");
    } else {
        updateEmotionStatus("😐", "正常");
    }
}

function updateEmotionStatus(emoji, text) {
    document.getElementById("emotion-status").textContent = `${emoji} ${text}`;
}

function clearChat() {
    document.getElementById("chat-container").innerHTML =
        `<div class="text-center text-gray-400 text-sm py-8">點擊「開始對話」來啟動陪伴系統</div>`;
    chatCount = 0;
    document.getElementById("chat-count").textContent = "0";
    document.getElementById("emotion-status").textContent = "等待對話...";
    document.getElementById("text-input").disabled = true;
    document.getElementById("send-btn").disabled = true;
    document.getElementById("record-btn").disabled = true;
    document.getElementById("start-btn").textContent = "🌟 開始對話";
    document.getElementById("start-btn").disabled = false;
}

try {
    loadElderProfile();
} catch(e) {
    console.error("loadElderProfile 失敗：", e);
}

try {
    document.getElementById("text-input").addEventListener("keypress", (e) => {
        if (e.key === "Enter") sendMessage();
    });
    document.getElementById("record-btn").addEventListener("click", toggleRecording);
    document.getElementById("send-btn").addEventListener("click", sendMessage);
    document.getElementById("start-btn").addEventListener("click", startSession);
    document.getElementById("clear-btn").addEventListener("click", clearChat);
} catch(e) {
    console.error("事件綁定失敗：", e);
}