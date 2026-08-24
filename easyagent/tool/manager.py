import asyncio
import importlib
import json
import pkgutil
from inspect import Parameter, iscoroutinefunction, signature
from pathlib import Path
from typing import Any

from easyagent.model.schema import ToolCall
from easyagent.tool.base import Tool, ToolContext, ToolResult


class ToolManager:
    """Registry of tools with lazy built-in discovery."""

    def __init__(self, *, discover_builtin: bool = True):
        self._tools: dict[str, Any] = {}
        self._invokers: dict[str, Tool] = {}
        self._discovered = not discover_builtin

    def register(self, tool: Any) -> None:
        self._validate_tool(tool)
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        init = getattr(tool, "init", None)
        if callable(init):
            init()
        self._tools[tool.name] = tool
        self._invokers[tool.name] = (
            tool if _uses_context_interface(tool) else _LegacyToolAdapter(tool)
        )

    def get(self, name: str) -> Any | None:
        if name not in self._tools:
            self._ensure_discovered()
        return self._tools.get(name)

    def registered_names(self) -> frozenset[str]:
        """Return registered tool names without triggering discovery."""
        return frozenset(self._tools)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        if name not in self._invokers:
            self._ensure_discovered()
        tool = self._invokers.get(name)
        if tool is None:
            return ToolResult(content=f"Tool '{name}' not found", is_error=True)
        value = await tool.execute(arguments, context)
        if isinstance(value, ToolResult):
            return value
        return ToolResult(content="" if value is None else str(value))

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
        self._invokers.clear()
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
    def _tool_to_schema(tool: Any) -> dict[str, Any]:
        return {
            "type": tool.type,
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": getattr(tool, "parameters", {"type": "object", "properties": {}}),
            },
        }

    @staticmethod
    def _validate_tool(tool: Any) -> None:
        for attribute in ("name", "type", "description", "execute"):
            if not hasattr(tool, attribute):
                raise TypeError(f"{tool} is missing required tool attribute '{attribute}'")
        if not isinstance(tool.name, str) or not tool.name:
            raise TypeError("Tool name must be a non-empty string")


class _LegacyToolAdapter(Tool):
    """Adapt legacy ``execute(**kwargs)`` tools to the context-aware Interface."""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = tool.name
        self.type = tool.type
        self.description = tool.description
        self.parameters = getattr(
            tool,
            "parameters",
            {"type": "object", "properties": {}},
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        call_kwargs = _bind_legacy_kwargs(
            self._tool.execute,
            arguments,
            context.session,
        )
        if iscoroutinefunction(self._tool.execute):
            value = await self._tool.execute(**call_kwargs)
        else:
            value = await asyncio.to_thread(self._tool.execute, **call_kwargs)
        if isinstance(value, ToolResult):
            return value
        return ToolResult(content="" if value is None else str(value))


def _bind_legacy_kwargs(
    func: Any,
    arguments: dict[str, Any],
    session: Any,
) -> dict[str, Any]:
    params = signature(func).parameters
    bound = {key.strip().rstrip(":").strip(): value for key, value in arguments.items()}
    if "session" in params or any(
        parameter.kind == Parameter.VAR_KEYWORD for parameter in params.values()
    ):
        bound["session"] = session
    return bound


def _uses_context_interface(tool: Any) -> bool:
    """Return whether a tool explicitly opts into the context-aware contract."""
    return getattr(tool, "context_aware", False) is True


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

