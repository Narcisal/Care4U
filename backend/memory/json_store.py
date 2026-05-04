import json
import uuid
from datetime import datetime
from pathlib import Path
from .memory_manager import MemoryManager

DATA_DIR = Path(__file__).parent.parent / "data" / "elders"

class JsonMemoryStore(MemoryManager):

    def _get_path(self, elder_id: str) -> Path:
        return DATA_DIR / f"{elder_id}.json"

    def _get_conv_path(self, elder_id: str) -> Path:
        return DATA_DIR / f"{elder_id}_conversation.json"

    def get_profile(self, elder_id: str) -> dict:
        path = self._get_path(elder_id)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_conversation(self, elder_id: str, history: list) -> bool:
        try:
            data = {
                "elder_id": elder_id,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "history": history[-50:]
            }
            path = self._get_conv_path(elder_id)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"對話記憶儲存失敗：{e}")
            return False

    def load_conversation(self, elder_id: str) -> list:
        path = self._get_conv_path(elder_id)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("history", [])
        except Exception as e:
            print(f"對話記憶載入失敗：{e}")
            return []

    def clear_conversation(self, elder_id: str) -> bool:
        path = self._get_conv_path(elder_id)
        if path.exists():
            path.unlink()
        return True

    def add_event(self, elder_id: str, event: dict) -> bool:
        profile = self.get_profile(elder_id)
        if not profile:
            return False
        event["id"] = str(uuid.uuid4())[:8]
        event["date"] = datetime.now().strftime("%Y-%m-%d")
        profile["recent_events"].append(event)
        profile["recent_events"] = profile["recent_events"][-50:]
        return self._save(elder_id, profile)

    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        profile = self.get_profile(elder_id)
        events = profile.get("recent_events", [])
        return events[-limit:]

    def get_important_memories(self, elder_id: str,
                                importance_threshold: float = 0.7,
                                limit: int = 10) -> list:
        """
        撈出重要分數高於門檻的長期記憶
        預設只撈 importance >= 0.7 的事件（長期記憶）
        """
        profile = self.get_profile(elder_id)
        events = profile.get("recent_events", [])

        important = [
            e for e in events
            if e.get("importance", 0) >= importance_threshold
        ]

        # 依重要分數由高到低排序，取前 limit 筆
        important.sort(key=lambda x: x.get("importance", 0), reverse=True)
        return important[:limit]

    def get_recent_conversation_summary(self, elder_id: str,
                                         limit: int = 6) -> list:
        """
        取得最近幾則對話，用於注入 Prompt
        只取 user 說的話，不包含 AI 回應
        """
        history = self.load_conversation(elder_id)
        user_messages = [
            msg for msg in history
            if msg.get("role") == "user"
        ]
        return user_messages[-limit:]

    def update_profile(self, elder_id: str, data: dict) -> bool:
        profile = self.get_profile(elder_id)
        if not profile:
            return False
        profile.update(data)
        return self._save(elder_id, profile)

    def _save(self, elder_id: str, data: dict) -> bool:
        try:
            path = self._get_path(elder_id)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"儲存失敗：{e}")
            return False