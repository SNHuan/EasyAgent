from abc import abstractmethod
from typing import Any

from agent.base import BaseAgent
from memory.base import BaseMemory
from model.base import BaseLLM
from model.schema import ToolCall
from tool import ToolManager

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

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        tool = _manager.get(name)
        return tool.execute(**arguments) if tool else f"Tool '{name}' not found"

    @abstractmethod
    async def run(self, user_input: str) -> str:
        pass

