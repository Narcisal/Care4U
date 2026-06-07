from abc import ABC, abstractmethod
from typing import Literal


BiographyUpdateResult = Literal["updated", "skipped", "failed"]


class MemoryManager(ABC):

    @abstractmethod
    def get_profile(self, elder_id: str) -> dict:
        pass

    @abstractmethod
    def save_profile(self, elder_id: str, profile: dict) -> bool:
        pass

    @abstractmethod
    def add_event(self, elder_id: str, event: dict) -> int | bool:
        pass

    @abstractmethod
    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        pass

    @abstractmethod
    def update_profile(self, elder_id: str, data: dict) -> bool:
        pass

    @abstractmethod
    def append_family_note(self, elder_id: str, note_dict: dict) -> bool:
        pass

    @abstractmethod
    def delete_family_note_at(self, elder_id: str, index: int) -> bool:
        pass

    @abstractmethod
    def set_persona(self, elder_id: str, persona_id: str, persona_dict: dict) -> bool:
        pass

    @abstractmethod
    def add_persona_auto(self, elder_id: str, persona_dict: dict) -> str | None:
        pass

    @abstractmethod
    def delete_persona(self, elder_id: str, persona_id: str) -> bool:
        pass

    @abstractmethod
    def set_active_persona(self, elder_id: str, persona_id: str) -> bool:
        pass

    @abstractmethod
    def set_persona_field(
        self,
        elder_id: str,
        persona_id: str,
        field: str,
        value,
    ) -> bool:
        pass

    @abstractmethod
    def set_biography(
        self,
        elder_id: str,
        biography_dict: dict,
        *,
        skip_if_manual: bool = False,
        preserve_sources: bool = False,
    ) -> BiographyUpdateResult:
        pass

    @abstractmethod
    def update_basic_fields(self, elder_id: str, fields_dict: dict) -> bool:
        pass

    @abstractmethod
    def save_conversation(self, elder_id: str, history: list, persona_id: str = "ai") -> bool:
        pass

    @abstractmethod
    def load_conversation(self, elder_id: str, persona_id: str = "ai") -> list:
        pass

    @abstractmethod
    def clear_conversation(self, elder_id: str, persona_id: str = "ai") -> bool:
        pass

    @abstractmethod
    def get_recent_conversation_summary(self, elder_id: str, limit: int = 6, persona_id: str = "ai") -> list:
        pass
