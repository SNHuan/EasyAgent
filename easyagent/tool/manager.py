import importlib
import json
import pkgutil
from pathlib import Path
from typing import Any

from easyagent.model.schema import ToolCall
from easyagent.tool.base import Tool


class ToolManager:
    """Registry of tools with lazy built-in discovery."""

    def __init__(self, *, discover_builtin: bool = True):
        self._tools: dict[str, Tool] = {}
        self._discovered = not discover_builtin

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError(f"{tool} does not satisfy Tool protocol")
        tool.init()
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        if name not in self._tools:
            self._ensure_discovered()
        return self._tools.get(name)

    def get_schema(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """Get tool schema for API requests"""
        self._ensure_discovered()
        if names is not None:
            tools = [self._tools[n] for n in names if n in self._tools]
        else:
            tools = list(self._tools.values())
        return [self._tool_to_schema(t) for t in tools]

    def _ensure_discovered(self) -> None:
        """Lazy auto-discover built-in tools (only once)"""
        if self._discovered:
            return
        self._discovered = True
        _discover_builtin_tools()

    def reset(self) -> None:
        """Reset for testing"""
        self._tools.clear()
        self._discovered = False

    def format_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        """Format tool_calls for message history"""
        return [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in tool_calls
        ]

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
    """Class decorator: register a tool on the process default registry."""
    DEFAULT_TOOL_MANAGER.register(cls())
    return cls


def _discover_builtin_tools() -> None:
    """Scan and import all tool modules under easyagent/tool/"""
    tool_dir = Path(__file__).parent
    for _, name, ispkg in pkgutil.walk_packages([str(tool_dir)]):
        if name.startswith("_") or name in ("base", "manager"):
            continue
        module_name = f"easyagent.tool.{name}"
        try:
            importlib.import_module(module_name)
        except ImportError:
            continue
        if ispkg:
            subdir = tool_dir / name
            for _, subname, _ in pkgutil.walk_packages([str(subdir)]):
                if subname.startswith("_"):
                    continue
                try:
                    importlib.import_module(f"{module_name}.{subname}")
                except ImportError:
                    pass


DEFAULT_TOOL_MANAGER = ToolManager()

