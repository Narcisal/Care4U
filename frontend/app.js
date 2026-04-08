const ELDER_ID = "W001";
const API_BASE = "http://127.0.0.1:8000";

let chatCount = 0;

// ====== 初始化 ======
async function loadElderProfile() {
    try {
        const res = await fetch(`${API_BASE}/api/profile/${ELDER_ID}`);
        const profile = await res.json();
        document.getElementById("elder-name").textContent = profile.name || "未知";
    } catch (e) {
        document.getElementById("elder-name").textContent = "載入失敗";
    }
}

// ====== 開始對話 ======
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

        // 顯示問候訊息
        addMessage("ai", data.message);
        
        // 啟用輸入
        document.getElementById("text-input").disabled = false;
        document.getElementById("send-btn").disabled = false;
        document.getElementById("text-input").focus();

        btn.textContent = "✅ 對話進行中";
        updateEmotionStatus("😊", "正常");

    } catch (e) {
        btn.textContent = "❌ 啟動失敗，請重試";
        btn.disabled = false;
        addMessage("system", "系統啟動失敗，請確認後端是否正常運行。");
    }
}

// ====== 送出訊息 ======
async function sendMessage() {
    const input = document.getElementById("text-input");
    const message = input.value.trim();
    if (!message) return;

    // 顯示使用者訊息
    addMessage("user", message);
    input.value = "";

    // 顯示 AI 思考中
    const thinkingId = addThinking();

    try {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ elder_id: ELDER_ID, message: message })
        });
        const data = await res.json();

        // 移除思考中，顯示回應
        removeThinking(thinkingId);
        addMessage("ai", data.message);

        // 更新對話輪數
        chatCount++;
        document.getElementById("chat-count").textContent = chatCount;

        // 偵測情緒關鍵字更新狀態
        updateEmotionFromMessage(message);

    } catch (e) {
        removeThinking(thinkingId);
        addMessage("system", "回應失敗，請稍後再試。");
    }
}

// ====== 新增訊息泡泡 ======
function addMessage(role, text) {
    const container = document.getElementById("chat-container");
    
    // 清除初始提示文字
    const placeholder = container.querySelector(".text-center");
    if (placeholder) placeholder.remove();

    const wrapper = document.createElement("div");
    
    if (role === "ai") {
        wrapper.className = "flex items-start gap-2";
        wrapper.innerHTML = `
            <div class="text-2xl">🤖</div>
            <div class="chat-bubble-ai text-white px-4 py-3 rounded-2xl rounded-tl-none max-w-xs lg:max-w-md shadow">
                <p class="text-base leading-relaxed">${text}</p>
            </div>
        `;
    } else if (role === "user") {
        wrapper.className = "flex items-start gap-2 justify-end";
        wrapper.innerHTML = `
            <div class="chat-bubble-user text-white px-4 py-3 rounded-2xl rounded-tr-none max-w-xs lg:max-w-md shadow">
                <p class="text-base leading-relaxed">${text}</p>
            </div>
            <div class="text-2xl">👴</div>
        `;
    } else {
        wrapper.className = "text-center text-gray-400 text-sm";
        wrapper.textContent = text;
    }

    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

// ====== 思考中動畫 ======
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

// ====== 情緒偵測 ======
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

// ====== 清除對話 ======
function clearChat() {
    const container = document.getElementById("chat-container");
    container.innerHTML = `<div class="text-center text-gray-400 text-sm py-8">點擊「開始對話」來啟動陪伴系統</div>`;
    chatCount = 0;
    document.getElementById("chat-count").textContent = "0";
    document.getElementById("emotion-status").textContent = "等待對話...";
    document.getElementById("text-input").disabled = true;
    document.getElementById("send-btn").disabled = true;
    document.getElementById("start-btn").textContent = "🌟 開始對話";
    document.getElementById("start-btn").disabled = false;
}

// ====== Enter 鍵送出 ======
document.addEventListener("DOMContentLoaded", () => {
    loadElderProfile();
    document.getElementById("text-input").addEventListener("keypress", (e) => {
        if (e.key === "Enter") sendMessage();
    });
});