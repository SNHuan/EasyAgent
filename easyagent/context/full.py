from __future__ import annotations

from typing import Any

from easyagent.context.base import BaseContext
from easyagent.memory.base import BaseMemory


class FullContext(BaseContext):
    async def build_messages(
        self,
        memory: BaseMemory,
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(message.to_api_dict() for message in memory.get_all())
        return messages

    def clone(self) -> BaseContext:
        return FullContext()
