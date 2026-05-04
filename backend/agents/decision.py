from backend.agents.magic_ai import MagicAI
from backend.agents.i_safe import ISafe
from datetime import datetime
import collections

_agent_logs = collections.deque(maxlen=100)

def _log(agent: str, action: str, detail: str):
    _agent_logs.appendleft({
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "action": action,
        "detail": detail
    })

def get_logs() -> list:
    return list(_agent_logs)

# 每個 elder_id 對應各自的 Agent 實例
_magic_agents: dict[str, MagicAI] = {}
_isafe_agents: dict[str, ISafe] = {}


def _get_magic(elder_id: str) -> MagicAI:
    if elder_id not in _magic_agents:
        _magic_agents[elder_id] = MagicAI(elder_id)
    return _magic_agents[elder_id]


def _get_isafe(elder_id: str) -> ISafe:
    if elder_id not in _isafe_agents:
        _isafe_agents[elder_id] = ISafe(elder_id)
    return _isafe_agents[elder_id]


def clear_agent(elder_id: str):
    """儲存長者資料後呼叫，清除快取讓 Agent 重新載入"""
    _magic_agents.pop(elder_id, None)
    _isafe_agents.pop(elder_id, None)


class Decision:
    """
    決策代理人，協調 MagicAI 與 iSafe。
    main.py 只需要跟 Decision 說話，不需要直接碰其他 Agent。
    """

    def __init__(self, elder_id: str):
        self.elder_id = elder_id
        self.magic = _get_magic(elder_id)
        self.isafe = _get_isafe(elder_id)

    def greet(self) -> dict:
        """開始對話，取得問候語"""
        greeting = self.magic.greet()
        return {
            "message": greeting,
            "emotion": "normal",
            "elder_id": self.elder_id
        }

    def chat(self, user_message: str) -> dict:
        _log("iSafe", "分析中", f"收到訊息：{user_message[:20]}...")
        safety = self.isafe.analyze(user_message)
        _log("iSafe", "分析完成", f"emotion={safety['emotion']}, urgent={safety['is_urgent']}")

        _log("Decision", "協調中", "呼叫 MagicAI 生成回應")
        response = self.magic.chat(user_message)
        _log("MagicAI", "回應完成", "已儲存對話記憶")

        # 偵測是否需要生成圖片
        image_data = None
        from backend.tools.image_gen import detect_image_trigger, generate_image
        trigger = detect_image_trigger(user_message)
        if trigger:
            _log("Decision", "圖片生成", f"偵測到 {trigger} 話題，生成圖片中...")
            image_data = generate_image(user_message, trigger)
            if image_data:
                _log("Decision", "圖片完成", "圖片生成成功")
            else:
                _log("Decision", "圖片失敗", "圖片生成失敗，略過")

        _log("Decision", "完成", f"emotion={safety['emotion']} → TTS 語調調整")

        return {
            "message": response,
            "emotion": safety["emotion"],
            "is_urgent": safety["is_urgent"],
            "sentiment": safety["sentiment"],
            "elder_id": self.elder_id,
            "history_length": len(self.magic.get_history()),
            "image": image_data  # 新增
        }

    def get_history(self) -> list:
        return self.magic.get_history()

    def get_safety_status(self) -> dict:
        return self.isafe.get_safety_status()

    @property
    def profile(self):
        return self.magic.profile