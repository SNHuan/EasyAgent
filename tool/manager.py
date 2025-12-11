import json
from typing import Any

from model.schema import ToolCall
from tool.base import Tool


class ToolManager:
    """工具管理器单例"""

    _instance: "ToolManager | None" = None
    _tools: dict[str, Tool]

    def __new__(cls) -> "ToolManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError(f"{tool} does not satisfy Tool protocol")
        tool.init()
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_schema(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """获取工具 schema 用于 API 请求"""
        if names:
            tools = [self._tools[n] for n in names if n in self._tools]
        else:
            tools = list(self._tools.values())
        return [self._tool_to_schema(t) for t in tools]

    def format_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        """格式化 tool_calls 用于消息历史"""
        return [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in tool_calls
        ]

    def clear(self) -> None:
        self._tools.clear()

    @staticmethod
    def _tool_to_schema(tool: Tool) -> dict[str, Any]:
        return {
            "type": tool.type,
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": getattr(tool, "parameters", {"type": "object", "properties": {}}),
            },
        }


def register_tool(cls: type) -> type:
    """类装饰器：自动注册 tool 到 ToolManager"""
    ToolManager().register(cls())
    return cls

