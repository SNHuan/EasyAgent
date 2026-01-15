from abc import abstractmethod
from inspect import iscoroutinefunction
from typing import Any

from easyagent.agent.base import BaseAgent
from easyagent.memory.base import BaseMemory
from easyagent.model.base import BaseLLM
from easyagent.model.schema import ToolCall
from easyagent.tool import ToolManager

_manager = ToolManager()


class ToolAgent(BaseAgent):
    """Base Agent with tool calling support"""

    def __init__(
        self,
        model: BaseLLM,
        system_prompt: str = "",
        tools: list[str] | None = None,
        memory: BaseMemory | None = None,
    ):
        super().__init__(model, system_prompt, memory)
        self._tool_names = tools or []

    def _get_tools_schema(self) -> list[dict[str, Any]]:
        return _manager.get_schema(self._tool_names)

    def _format_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        return _manager.format_tool_calls(tool_calls)

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        tool = _manager.get(name)
        if not tool:
            return f"Tool '{name}' not found"
        # Support both sync and async execute
        if iscoroutinefunction(tool.execute):
            return await tool.execute(**arguments)
        return tool.execute(**arguments)

    @abstractmethod
    async def run(self, user_input: str) -> str:
        pass

