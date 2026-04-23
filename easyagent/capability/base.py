from __future__ import annotations

from abc import ABC
from typing import Any


class BaseCapability(ABC):
    def on_attach(self, agent: Any) -> None:
        pass

    async def on_enter(self, agent: Any, session: Any) -> None:
        pass

    async def on_exit(self, agent: Any, session: Any) -> None:
        pass

    def get_system_prompt_parts(self, agent: Any, session: Any) -> list[str]:
        return []

    def get_tool_schemas(self, agent: Any, session: Any) -> list[dict[str, Any]]:
        return []

    async def handle_tool_call(
        self,
        agent: Any,
        session: Any,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        return None
