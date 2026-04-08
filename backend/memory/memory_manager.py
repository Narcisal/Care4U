from abc import ABC, abstractmethod
from typing import Optional

class MemoryManager(ABC):
    
    @abstractmethod
    def get_profile(self, elder_id: str) -> dict:
        """取得長者完整資料"""
        pass

    @abstractmethod
    def add_event(self, elder_id: str, event: dict) -> bool:
        """新增一筆事件記憶"""
        pass

    @abstractmethod
    def get_recent_events(self, elder_id: str, limit: int = 5) -> list:
        """取得最近幾筆事件"""
        pass

    @abstractmethod
    def update_profile(self, elder_id: str, data: dict) -> bool:
        """更新長者基本資料"""
        pass