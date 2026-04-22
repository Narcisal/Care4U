from backend.agents.magic_ai import MagicAI
from backend.agents.i_safe import ISafe

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
        """
        完整對話流程：
        1. iSafe 分析安全與情緒
        2. MagicAI 生成回應
        3. Decision 整合結果回傳
        """
        # 步驟一：iSafe 分析
        safety = self.isafe.analyze(user_message)

        # 步驟二：MagicAI 生成回應
        response = self.magic.chat(user_message)

        # 步驟三：整合回傳
        return {
            "message": response,
            "emotion": safety["emotion"],
            "is_urgent": safety["is_urgent"],
            "sentiment": safety["sentiment"],
            "elder_id": self.elder_id,
            "history_length": len(self.magic.get_history())
        }

    def get_history(self) -> list:
        return self.magic.get_history()

    def get_safety_status(self) -> dict:
        return self.isafe.get_safety_status()

    @property
    def profile(self):
        return self.magic.profile