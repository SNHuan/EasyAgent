from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

from easyagent.mcp.adapter import MCPToolAdapter
from easyagent.mcp.base import MCPClientProtocol, MCPClientSource
from easyagent.mcp.fastmcp_client import FastMCPClientAdapter

if TYPE_CHECKING:
    from easyagent.tool import ToolManager


class MCPToolset:
    """Discover MCP tools and expose them as EasyAgent tools."""

    def __init__(self, client: MCPClientProtocol):
        self._client = client

    @classmethod
    def from_fastmcp(cls, source: MCPClientSource) -> "MCPToolset":
        return cls(FastMCPClientAdapter(source))

    async def load_tools(
        self,
        *,
        tags: Iterable[str] | None = None,
    ) -> list[MCPToolAdapter]:
        infos = await self._client.list_tools()
        wanted_tags = {str(tag) for tag in tags or []}
        if wanted_tags:
            infos = [info for info in infos if info.tags & wanted_tags]
        return [MCPToolAdapter(info, self._client) for info in infos]

    async def close(self) -> None:
        await self._client.close()


async def load_mcp_tools(
    source: MCPClientSource,
    *,
    servers: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
) -> list[MCPToolAdapter]:
    """Load MCP tools from a FastMCP source.

    ``servers`` filters a FastMCP ``{"mcpServers": ...}`` config by server
    name before discovery. ``tags`` filters discovered tools by FastMCP tool
    tags stored in ``meta["_fastmcp"]["tags"]``.
    """

    selected_source = _filter_mcp_servers(source, servers)
    return await MCPToolset.from_fastmcp(selected_source).load_tools(tags=tags)


async def register_mcp_tools(
    tool_manager: "ToolManager",
    source: MCPClientSource,
    *,
    servers: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
) -> list[str]:
    """Load MCP tools and register them into an EasyAgent ToolManager."""

    tools = await load_mcp_tools(source, servers=servers, tags=tags)
    names: list[str] = []
    for tool in tools:
        tool_manager.register(tool)
        names.append(tool.name)
    return names


def _filter_mcp_servers(
    source: MCPClientSource,
    servers: Iterable[str] | None,
) -> MCPClientSource:
    wanted = {str(server) for server in servers or []}
    if not wanted:
        return source
    if not isinstance(source, dict) or "mcpServers" not in source:
        return source

    config = dict(source)
    mcp_servers = source.get("mcpServers") or {}
    if not isinstance(mcp_servers, dict):
        return source
    config["mcpServers"] = {
        name: value for name, value in mcp_servers.items()
        if name in wanted
    }
    return config
