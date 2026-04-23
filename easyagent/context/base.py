from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from easyagent.memory.base import BaseMemory


class BaseContext(ABC):
    @abstractmethod
    async def build_messages(
        self,
        memory: BaseMemory,
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def clone(self) -> "BaseContext":
        pass
