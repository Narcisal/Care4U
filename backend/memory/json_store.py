import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable
from .memory_manager import BiographyUpdateResult, MemoryManager
from backend.utils.validators import validate_elder_id, validate_persona_id

DATA_DIR = Path(__file__).parent.parent / "data" / "elders"

# Per-file locks so concurrent requests to different elders never block each other.
_file_locks: dict[str, threading.Lock] = {}
_file_locks_mutex = threading.Lock()


def _get_file_lock(path: str) -> threading.Lock:
    with _file_locks_mutex:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


class JsonMemoryStore(MemoryManager):
    MAX_EVENTS = 80
    IMPORTANT_KEEP_LIMIT = 40

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _get_path(self, elder_id: str) -> Path:
        return DATA_DIR / f"{validate_elder_id(elder_id)}.json"

    def _get_conv_path(self, elder_id: str, persona_id: str = "ai") -> Path:
        valid_elder_id = validate_elder_id(elder_id)
        valid_persona_id = validate_persona_id(persona_id or "ai")
        return DATA_DIR / f"{valid_elder_id}_{valid_persona_id}_conv.json"

    # ------------------------------------------------------------------
    # Atomic write primitives
    # ------------------------------------------------------------------

    def _write_profile_unlocked(self, path: Path, data: dict) -> bool:
        """Write atomically. Caller MUST already hold _get_file_lock(str(path))."""
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except Exception as e:
            print(f"寫入失敗：{e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    def _save(self, elder_id: str, data: dict) -> bool:
        """Atomic profile write (acquires lock internally)."""
        path = self._get_path(elder_id)
        lock = _get_file_lock(str(path))
        with lock:
            return self._write_profile_unlocked(path, data)

    def save_profile(self, elder_id: str, profile: dict) -> bool:
        return self._save(elder_id, profile)

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self, elder_id: str) -> dict:
        path = self._get_path(elder_id)
        lock = _get_file_lock(str(path))
        with lock:
            if not path.exists():
                return {}
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"讀取失敗：{e}")
                return {}

    def update_profile(self, elder_id: str, data: dict) -> bool:
        path = self._get_path(elder_id)
        lock = _get_file_lock(str(path))
        with lock:
            if not path.exists():
                return False
            try:
                with open(path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception as e:
                print(f"讀取失敗：{e}")
                return False
            profile.update(data)
            return self._write_profile_unlocked(path, profile)

    def _mutate_profile(
        self,
        elder_id: str,
        mutator: Callable[[dict], bool],
        *,
        create: bool = False,
    ) -> bool:
        path = self._get_path(elder_id)
        lock = _get_file_lock(str(path))
        with lock:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        profile = json.load(f)
                except Exception as e:
                    print(f"讀取失敗：{e}")
                    return False
            elif create:
                profile = {"elder_id": elder_id}
            else:
                return False

            if not mutator(profile):
                return False
            return self._write_profile_unlocked(path, profile)

    def append_family_note(self, elder_id: str, note_dict: dict) -> bool:
        def append(profile: dict) -> bool:
            profile.setdefault("family_notes", []).append(note_dict)
            return True

        return self._mutate_profile(elder_id, append)

    def delete_family_note_at(self, elder_id: str, index: int) -> bool:
        def delete(profile: dict) -> bool:
            notes = profile.get("family_notes", [])
            if not 0 <= index < len(notes):
                raise IndexError(
                    f"family note index {index} out of range ({len(notes)})"
                )
            notes.pop(index)
            profile["family_notes"] = notes
            return True

        return self._mutate_profile(elder_id, delete)

    def set_persona(self, elder_id: str, persona_id: str, persona_dict: dict) -> bool:
        persona_id = validate_persona_id(persona_id)

        def set_value(profile: dict) -> bool:
            profile.setdefault("personas", {})[persona_id] = persona_dict
            return True

        return self._mutate_profile(elder_id, set_value)

    def add_persona_auto(self, elder_id: str, persona_dict: dict) -> str | None:
        allocated_id: str | None = None

        def add(profile: dict) -> bool:
            nonlocal allocated_id
            personas = profile.setdefault("personas", {})
            numbers = [
                int(match.group(1))
                for persona_id in personas
                if (match := re.fullmatch(r"persona_(\d+)", persona_id))
            ]
            allocated_id = validate_persona_id(
                f"persona_{max(numbers, default=0) + 1}"
            )
            personas[allocated_id] = persona_dict
            return True

        return allocated_id if self._mutate_profile(elder_id, add) else None

    def delete_persona(self, elder_id: str, persona_id: str) -> bool:
        persona_id = validate_persona_id(persona_id)

        def delete(profile: dict) -> bool:
            personas = profile.get("personas", {})
            if persona_id not in personas:
                raise KeyError(persona_id)
            personas.pop(persona_id)
            if profile.get("active_persona") == persona_id:
                profile["active_persona"] = "ai"
            return True

        return self._mutate_profile(elder_id, delete)

    def set_active_persona(self, elder_id: str, persona_id: str) -> bool:
        persona_id = validate_persona_id(persona_id)

        def set_active(profile: dict) -> bool:
            if persona_id not in profile.get("personas", {}):
                return False
            profile["active_persona"] = persona_id
            return True

        return self._mutate_profile(elder_id, set_active)

    def set_persona_field(
        self,
        elder_id: str,
        persona_id: str,
        field: str,
        value,
    ) -> bool:
        persona_id = validate_persona_id(persona_id)

        def set_field(profile: dict) -> bool:
            persona = profile.get("personas", {}).get(persona_id)
            if persona is None:
                return False
            persona[field] = value
            return True

        return self._mutate_profile(elder_id, set_field)

    def set_biography(
        self,
        elder_id: str,
        biography_dict: dict,
        *,
        skip_if_manual: bool = False,
        preserve_sources: bool = False,
    ) -> BiographyUpdateResult:
        result: BiographyUpdateResult = "failed"

        def set_value(profile: dict) -> bool:
            nonlocal result
            existing = profile.get("elder_biography", {})
            if skip_if_manual and existing.get("manually_edited"):
                result = "skipped"
                return False

            value = dict(biography_dict)
            if preserve_sources:
                value["sources"] = list(existing.get("sources", []))
            profile["elder_biography"] = value
            profile["biography_usage_count"] = 0
            result = "updated"
            return True

        written = self._mutate_profile(elder_id, set_value)
        if result == "skipped":
            return result
        return "updated" if written else "failed"

    def update_basic_fields(self, elder_id: str, fields_dict: dict) -> bool:
        allowed_fields = {
            "name",
            "gender",
            "cognitive_status",
            "persona",
            "health_notes",
            "birth_year",
        }
        if not set(fields_dict).issubset(allowed_fields):
            return False

        def update(profile: dict) -> bool:
            profile.setdefault("recent_events", [])
            profile.setdefault("memory_summary", {})
            profile.setdefault("elder_biography", {})
            profile.setdefault("biography_usage_count", 0)
            profile.update(fields_dict)
            return True

        return self._mutate_profile(elder_id, update, create=True)

    # ------------------------------------------------------------------
    # Conversation persistence (per elder + persona)
    # ------------------------------------------------------------------

    def save_conversation(self, elder_id: str, history: list, persona_id: str = "ai") -> bool:
        path = self._get_conv_path(elder_id, persona_id)
        lock = _get_file_lock(str(path))
        tmp = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        try:
            data = {
                "elder_id": elder_id,
                "persona_id": persona_id or "ai",
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "history": history[-20:],
            }
            with lock:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            return True
        except Exception as e:
            print(f"對話記憶儲存失敗：{e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    def load_conversation(self, elder_id: str, persona_id: str = "ai") -> list:
        path = self._get_conv_path(elder_id, persona_id)
        lock = _get_file_lock(str(path))
        with lock:
            if not path.exists():
                return []
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                history = data.get("history", [])
                # Backfill missing fields for messages saved before the timestamp / iSafe fix.
                fallback_date = (data.get("updated_at") or "")[:10]  # "YYYY-MM-DD"
                for msg in history:
                    if not msg.get("date"):
                        msg["date"] = fallback_date
                    if not msg.get("time"):
                        msg["time"] = ""
                    # Model messages from before the iSafe patch lack escalation_level/sentiment.
                    # Default both so the admin table shows "● 正常" / "中性" instead of "—".
                    if msg.get("role") == "model":
                        if "escalation_level" not in msg:
                            msg["escalation_level"] = 0
                        if "sentiment" not in msg:
                            msg["sentiment"] = "neutral"
                return history
            except Exception as e:
                print(f"對話記憶載入失敗：{e}")
                return []

    def clear_conversation(self, elder_id: str, persona_id: str = "ai") -> bool:
        path = self._get_conv_path(elder_id, persona_id)
        lock = _get_file_lock(str(path))
        with lock:
            if path.exists():
                path.unlink()
        return True

    def get_recent_conversation_summary(self, elder_id: str, limit: int = 6, persona_id: str = "ai") -> list:
        history = self.load_conversation(elder_id, persona_id)
        return [msg for msg in history if msg.get("role") == "user"][-limit:]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def add_event(self, elder_id: str, event: dict) -> bool:
        path = self._get_path(elder_id)
        lock = _get_file_lock(str(path))
        with lock:
            if not path.exists():
                return False
            try:
                with open(path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception as e:
                print(f"讀取失敗：{e}")
                return False

            event["id"] = str(uuid.uuid4())[:8]
            if "spoken_at" in event:
                event["date"] = event["spoken_at"][:10]
                event["time"] = event["spoken_at"][11:]
            else:
                event["date"] = datetime.now().strftime("%Y-%m-%d")
                event["time"] = datetime.now().strftime("%H:%M:%S")
            event.setdefault("acknowledged", False)

            profile.setdefault("recent_events", []).append(event)
            profile["recent_events"] = self._trim_events(profile["recent_events"])
            return self._write_profile_unlocked(path, profile)

    def acknowledge_event_at(self, elder_id: str, index: int) -> bool:
        path = self._get_path(elder_id)
        lock = _get_file_lock(str(path))
        with lock:
            if not path.exists():
                return False
            try:
                with open(path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception as e:
                print(f"讀取長者事件失敗：{e}")
                return False

            events = profile.get("recent_events", [])
            if index < 0 or index >= len(events):
                return False
            events[index]["acknowledged"] = True
            events[index]["acknowledged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return self._write_profile_unlocked(path, profile)

    def acknowledge_events_by_tag(self, elder_id: str, tag: str) -> int:
        """Acknowledge all unacknowledged events that contain the given tag. Returns count."""
        path = self._get_path(elder_id)
        lock = _get_file_lock(str(path))
        with lock:
            if not path.exists():
                return 0
            try:
                with open(path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception as e:
                print(f"讀取長者事件失敗：{e}")
                return 0
            events = profile.get("recent_events", [])
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            count = 0
            for event in events:
                if event.get("acknowledged") is True:
                    continue
                if tag in (event.get("topic_tags") or []):
                    event["acknowledged"] = True
                    event["acknowledged_at"] = now
                    count += 1
            if count:
                self._write_profile_unlocked(path, profile)
            return count

    def _trim_events(self, events: list) -> list:
        if len(events) <= self.MAX_EVENTS:
            return events

        def is_unacknowledged_alert(event: dict) -> bool:
            tags = set(event.get("topic_tags") or [])
            return event.get("acknowledged") is not True and (
                event.get("escalation_level", 0) >= 2
                or bool(tags & {"安全警報", "緊急警報", "趨勢警報"})
            )

        selected: set[int] = set()
        alert_indexes = [
            index
            for index, event in enumerate(events)
            if is_unacknowledged_alert(event)
        ][-self.MAX_EVENTS:]
        selected.update(alert_indexes)

        remaining = self.MAX_EVENTS - len(selected)
        if remaining > 0:
            important_indexes = [
                index
                for index, event in enumerate(events)
                if index not in selected
                and (
                    event.get("importance", 0) >= 0.7
                    or event.get("memory_type") == "long"
                )
            ][-min(self.IMPORTANT_KEEP_LIMIT, remaining):]
            selected.update(important_indexes)

        remaining = self.MAX_EVENTS - len(selected)
        if remaining > 0:
            recent_indexes = [
                index
                for index in range(len(events))
                if index not in selected
            ][-remaining:]
            selected.update(recent_indexes)

        return [event for index, event in enumerate(events) if index in selected]

    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        profile = self.get_profile(elder_id)
        return profile.get("recent_events", [])[-limit:]

    def get_important_memories(
        self,
        elder_id: str,
        importance_threshold: float = 0.7,
        limit: int = 10,
        persona_id: str = None,
    ) -> list:
        profile = self.get_profile(elder_id)
        important = [
            e for e in profile.get("recent_events", [])
            if e.get("importance", 0) >= importance_threshold
            and (
                not persona_id
                or persona_id == "ai"
                or e.get("persona_id") in (None, "ai", persona_id)
            )
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
        """Lightweight token-overlap RAG fallback for demo mode."""
        profile = self.get_profile(elder_id)
        events = profile.get("recent_events", [])
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []

        scored = []
        for event in events:
            if persona_id and persona_id != "ai":
                ep = event.get("persona_id")
                if ep not in (None, "", "ai", persona_id):
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
        chinese = re.findall(r"[一-鿿]{2,}", value)
        chars: set[str] = set()
        for chunk in chinese:
            chars.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
            if len(chunk) <= 4:
                chars.add(chunk)
        return set(latin) | chars
