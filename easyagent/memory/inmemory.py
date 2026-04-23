from __future__ import annotations

from easyagent.memory.base import BaseMemory
from easyagent.model.schema import Message


class InMemoryMemory(BaseMemory):
    def __init__(self):
        self._messages: list[Message] = []

    def add(self, message: Message) -> None:
        self._messages.append(message)

    def get_all(self) -> list[Message]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def clone(self) -> BaseMemory:
        return InMemoryMemory()
