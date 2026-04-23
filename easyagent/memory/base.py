from __future__ import annotations

from abc import ABC, abstractmethod

from easyagent.model.schema import Message


class BaseMemory(ABC):
    @abstractmethod
    def add(self, message: Message) -> None:
        pass

    @abstractmethod
    def get_all(self) -> list[Message]:
        pass

    @abstractmethod
    def clear(self) -> None:
        pass

    @abstractmethod
    def clone(self) -> "BaseMemory":
        pass
