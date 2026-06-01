import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from .memory_manager import MemoryManager

DATA_DIR = Path(__file__).parent.parent / "data" / "elders"

class JsonMemoryStore(MemoryManager):
    MAX_EVENTS = 80
    IMPORTANT_KEEP_LIMIT = 40


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
                "history": history[-20:]
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
        if "spoken_at" in event:
            event["date"] = event["spoken_at"][:10]
            event["time"] = event["spoken_at"][11:]
        else:
            event["date"] = datetime.now().strftime("%Y-%m-%d")
            event["time"] = datetime.now().strftime("%H:%M:%S")
        profile.setdefault("recent_events", []).append(event)
        profile["recent_events"] = self._trim_events(profile["recent_events"])
        return self._save(elder_id, profile)

    def _trim_events(self, events: list) -> list:
        """Keep recent events while preserving high-importance memories."""
        if len(events) <= self.MAX_EVENTS:
            return events

        important = [
            e for e in events
            if e.get("importance", 0) >= 0.7 or e.get("memory_type") == "long"
        ][-self.IMPORTANT_KEEP_LIMIT:]
        important_ids = {e.get("id") for e in important if e.get("id")}
        recent = [
            e for e in events[-self.MAX_EVENTS:]
            if not e.get("id") or e.get("id") not in important_ids
        ]
        combined = important + recent
        return combined[-self.MAX_EVENTS:]

    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        profile = self.get_profile(elder_id)
        events = profile.get("recent_events", [])
        return events[-limit:]

    def get_important_memories(self, elder_id: str,
                                importance_threshold: float = 0.7,
                                limit: int = 10) -> list:
        profile = self.get_profile(elder_id)
        events = profile.get("recent_events", [])
        important = [
            e for e in events
            if e.get("importance", 0) >= importance_threshold
        ]
        important.sort(key=lambda x: x.get("importance", 0), reverse=True)
        return important[:limit]

    def search_similar_memories(
        self,
        elder_id: str,
        query: str,
        limit: int = 5,
        persona_id: str = None,
    ) -> list:
        """Lightweight JSON fallback RAG for demo mode.

        PostgreSQL/pgvector remains the preferred semantic search path. This
        fallback uses token overlap plus importance so demo mode can still show
        relevant historical memories when DB_ENABLED=false.
        """
        profile = self.get_profile(elder_id)
        events = profile.get("recent_events", [])
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []

        scored = []
        for event in events:
            if persona_id and persona_id != "ai":
                event_persona = event.get("persona_id")
                if event_persona not in (None, "", "ai", persona_id):
                    continue

            text = " ".join([
                str(event.get("event", "")),
                str(event.get("reason", "")),
                " ".join(event.get("topic_tags", []) or []),
            ])
            event_tokens = self._tokens(text)
            if not event_tokens:
                continue

            overlap = query_tokens & event_tokens
            if not overlap:
                continue

            importance = float(event.get("importance", 0) or 0)
            score = len(overlap) + importance
            row = dict(event)
            row["rag_score"] = round(score, 3)
            row["distance"] = max(0.0, 1.0 - min(score / 6.0, 1.0))
            scored.append(row)

        scored.sort(
            key=lambda e: (
                e.get("rag_score", 0),
                e.get("importance", 0),
                e.get("date", ""),
                e.get("time", ""),
            ),
            reverse=True,
        )
        return scored[:limit]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        value = str(text or "").lower()
        latin = re.findall(r"[a-z0-9]+", value)
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", value)
        chars = set()
        for chunk in chinese:
            chars.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
            if len(chunk) <= 4:
                chars.add(chunk)
        return set(latin) | chars

    def get_recent_conversation_summary(self, elder_id: str,
                                         limit: int = 6) -> list:
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
