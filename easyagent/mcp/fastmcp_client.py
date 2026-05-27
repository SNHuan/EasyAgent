from __future__ import annotations

from typing import Any

from easyagent.mcp.base import (
    MCPClientSource,
    MCPConnectionError,
    MCPToolError,
    MCPToolInfo,
    MCPToolResult,
    normalize_mcp_result,
)


class FastMCPClientAdapter:
    """EasyAgent MCP client wrapper backed by ``fastmcp.Client``."""

    def __init__(self, source: MCPClientSource):
        try:
            from fastmcp import Client
        except ImportError as exc:
            raise MCPConnectionError(
                "FastMCP support requires the optional dependency: "
                "pip install 'easy-agent-sdk[mcp]'"
            ) from exc

        self._client = Client(source)

    async def list_tools(self) -> list[MCPToolInfo]:
        try:
            async with self._client:
                tools = await self._client.list_tools()
        except Exception as exc:
            raise MCPConnectionError(f"Failed to list MCP tools: {exc}") from exc
        return [MCPToolInfo.from_mcp_tool(tool) for tool in tools]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        try:
            async with self._client:
                result = await self._client.call_tool(name, arguments or {})
        except Exception as exc:
            return MCPToolResult(content=str(exc), is_error=True, raw=exc)

        try:
            content = normalize_mcp_result(result)
        except Exception as exc:
            raise MCPToolError(f"Failed to normalize MCP tool result: {exc}") from exc
        return MCPToolResult(content=content, raw=result)

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()
