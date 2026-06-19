from dataclasses import dataclass
from typing import Any

import pytest

from easyagent.mcp import (
    MCPToolResult,
    MCPToolset,
    load_mcp_tools,
    normalize_mcp_content_block,
    normalize_mcp_result,
    register_mcp_tools,
)
from easyagent.mcp.toolset import _filter_mcp_servers
from easyagent.mcp.base import MCPToolInfo
from easyagent.tool import ToolManager


@dataclass
class RemoteTool:
    name: str
    description: str
    inputSchema: dict[str, Any]
    meta: dict[str, Any] | None = None


class FakeMCPClient:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo.from_mcp_tool(
                RemoteTool(
                    name="greet",
                    description="Greet a user.",
                    inputSchema={
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                    meta={"_fastmcp": {"tags": ["demo", "safe"]}},
                )
            )
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        args = arguments or {}
        self.calls.append((name, args))
        return MCPToolResult(content=f"Hello, {args['name']}!")

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_mcp_toolset_loads_easyagent_tools():
    client = FakeMCPClient()
    toolset = MCPToolset(client)

    tools = await toolset.load_tools()

    assert len(tools) == 1
    assert tools[0].name == "greet"
    assert tools[0].description == "Greet a user."
    assert tools[0].parameters["properties"]["name"]["type"] == "string"
    assert tools[0].tags == {"demo", "safe"}

    result = await tools[0].execute(name="Ada")

    assert result == "Hello, Ada!"
    assert client.calls == [("greet", {"name": "Ada"})]


@pytest.mark.asyncio
async def test_mcp_tool_adapter_registers_with_tool_manager():
    client = FakeMCPClient()
    tool = (await MCPToolset(client).load_tools())[0]
    manager = ToolManager(discover_builtin=False)

    manager.register(tool)
    schema = manager.get_schema(["greet"])[0]

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "greet"
    assert schema["function"]["parameters"]["required"] == ["name"]


@pytest.mark.asyncio
async def test_mcp_toolset_filters_by_fastmcp_tags():
    client = FakeMCPClient()
    toolset = MCPToolset(client)

    assert len(await toolset.load_tools(tags=["safe"])) == 1
    assert await toolset.load_tools(tags=["dangerous"]) == []


@pytest.mark.asyncio
async def test_register_mcp_tools_registers_and_returns_names():
    client = FakeMCPClient()
    manager = ToolManager(discover_builtin=False)

    names = []
    for tool in await MCPToolset(client).load_tools():
        manager.register(tool)
        names.append(tool.name)

    assert names == ["greet"]
    assert manager.get("greet") is not None


def test_filter_mcp_servers_selects_config_categories():
    source = {
        "mcpServers": {
            "literature": {"command": "python", "args": ["literature.py"]},
            "materials": {"command": "python", "args": ["materials.py"]},
        }
    }

    filtered = _filter_mcp_servers(source, ["literature"])

    assert list(filtered["mcpServers"]) == ["literature"]
    assert "materials" in source["mcpServers"]


def test_filter_mcp_servers_leaves_non_config_sources_unchanged():
    assert _filter_mcp_servers("./server.py", ["literature"]) == "./server.py"


def test_mcp_tool_result_formats_errors():
    result = MCPToolResult(content="boom", is_error=True)

    assert result.to_text() == "MCP tool error: boom"


def test_normalize_mcp_result_handles_content_blocks():
    assert normalize_mcp_result([{"type": "text", "text": "hello"}]) == "hello"
    assert normalize_mcp_content_block({"type": "image"}) == "[image]"


def test_normalize_mcp_result_handles_structured_content():
    class Result:
        structured_content = {"ok": True}

    assert normalize_mcp_result(Result()) == '{"ok": true}'


def test_normalize_mcp_result_prefers_structured_content_over_data():
    class RootLike:
        def __str__(self) -> str:
            return "Root()"

    class Result:
        data = [RootLike()]
        structured_content = {"result": [{"title": "Valid paper"}]}
        content = [{"type": "text", "text": '[{"title": "Valid paper"}]'}]

    result = normalize_mcp_result(Result())

    assert "Valid paper" in result
    assert "Root()" not in result


def test_normalize_mcp_result_prefers_content_over_data():
    class RootLike:
        def __str__(self) -> str:
            return "Root()"

    class Result:
        data = [RootLike()]
        content = [{"type": "text", "text": "plain tool output"}]

    assert normalize_mcp_result(Result()) == "plain tool output"
