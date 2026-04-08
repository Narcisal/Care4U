import json
import uuid
from datetime import datetime
from pathlib import Path
from .memory_manager import MemoryManager

DATA_DIR = Path(__file__).parent.parent / "data" / "elders"

class JsonMemoryStore(MemoryManager):

    def _get_path(self, elder_id: str) -> Path:
        return DATA_DIR / f"{elder_id}.json"

    def get_profile(self, elder_id: str) -> dict:
        path = self._get_path(elder_id)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def add_event(self, elder_id: str, event: dict) -> bool:
        profile = self.get_profile(elder_id)
        if not profile:
            return False
        event["id"] = str(uuid.uuid4())[:8]
        event["date"] = datetime.now().strftime("%Y-%m-%d")
        profile["recent_events"].append(event)
        # 只保留最近 50 筆，避免檔案無限成長
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