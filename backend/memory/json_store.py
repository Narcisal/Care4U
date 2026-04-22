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
        """對話記憶獨立存一個檔案，避免跟 profile 混在一起"""
        return DATA_DIR / f"{elder_id}_conversation.json"

    def get_profile(self, elder_id: str) -> dict:
        path = self._get_path(elder_id)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_conversation(self, elder_id: str, history: list) -> bool:
        """把對話歷史存到獨立 JSON 檔案"""
        try:
            data = {
                "elder_id": elder_id,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "history": history[-50:]  # 最多保留 20 則
            }
            path = self._get_conv_path(elder_id)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"對話記憶儲存失敗：{e}")
            return False

    def load_conversation(self, elder_id: str) -> list:
        """從 JSON 讀取上次的對話歷史"""
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
        """清除對話記憶（切換長者或手動清除時用）"""
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