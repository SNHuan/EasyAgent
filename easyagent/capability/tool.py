from __future__ import annotations

from inspect import Parameter, iscoroutinefunction, signature
from typing import Any

from easyagent.capability.base import BaseCapability
from easyagent.tool import ToolManager


class ToolCapability(BaseCapability):
    def __init__(self, tools: list[str] | None = None):
        self._default_tools = list(tools or [])
        self._manager = ToolManager()

    def on_attach(self, agent: Any) -> None:
        agent._default_tools.extend(
            tool_name for tool_name in self._default_tools if tool_name not in agent._default_tools
        )

    def get_tool_schemas(self, agent: Any, session: Any) -> list[dict[str, Any]]:
        return self._manager.get_schema(session.enabled_tools)

    async def handle_tool_call(
        self,
        agent: Any,
        session: Any,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        if tool_name not in session.enabled_tools:
            return None

        tool = self._manager.get(tool_name)
        if tool is None:
            return None

        call_kwargs = _bind_execute_kwargs(tool.execute, arguments, session)
        if iscoroutinefunction(tool.execute):
            return await tool.execute(**call_kwargs)
        return tool.execute(**call_kwargs)


def _bind_execute_kwargs(func: Any, arguments: dict[str, Any], session: Any) -> dict[str, Any]:
    sig = signature(func)
    params = sig.parameters
    bound = dict(arguments)

    if "session" in params:
        bound["session"] = session
        return bound

    if any(param.kind == Parameter.VAR_KEYWORD for param in params.values()):
        bound["session"] = session
    return bound
