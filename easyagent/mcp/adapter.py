from __future__ import annotations

from typing import Any

from easyagent.mcp.base import MCPClientProtocol, MCPToolInfo


class MCPToolAdapter:
    """Expose one remote MCP tool through EasyAgent's Tool protocol."""

    type = "function"

    def __init__(self, info: MCPToolInfo, client: MCPClientProtocol):
        self.name = info.name
        self.description = info.description
        self.parameters = info.input_schema or {"type": "object", "properties": {}}
        self.mcp_info = info
        self.tags = set(info.tags)
        self.meta = dict(info.meta)
        self.annotations = dict(info.annotations)
        self.output_schema = info.output_schema
        self._remote_name = info.remote_name or info.name
        self._client = client

    def init(self) -> None:
        pass

    async def execute(self, **kwargs: Any) -> str:
        result = await self._client.call_tool(self._remote_name, kwargs)
        return result.to_text()
