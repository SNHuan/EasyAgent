from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias, runtime_checkable


MCPClientSource: TypeAlias = str | dict[str, Any] | Any


@dataclass(slots=True)
class MCPToolInfo:
    """Transport-independent metadata for a remote MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    remote_name: str | None = None
    server_name: str | None = None
    tags: set[str] = field(default_factory=set)
    meta: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None

    @classmethod
    def from_mcp_tool(cls, tool: Any) -> "MCPToolInfo":
        name = str(getattr(tool, "name"))
        description = getattr(tool, "description", None) or f"MCP tool {name}"
        input_schema = (
            getattr(tool, "inputSchema", None)
            or getattr(tool, "input_schema", None)
            or {"type": "object", "properties": {}}
        )
        meta = _as_dict(getattr(tool, "meta", None) or getattr(tool, "_meta", None))
        annotations = _as_dict(getattr(tool, "annotations", None))
        output_schema = (
            getattr(tool, "outputSchema", None)
            or getattr(tool, "output_schema", None)
        )

        return cls(
            name=name,
            remote_name=name,
            description=description,
            input_schema=_as_schema(input_schema),
            tags=_extract_fastmcp_tags(meta),
            meta=meta,
            annotations=annotations,
            output_schema=_as_schema(output_schema) if output_schema else None,
        )


@dataclass(slots=True)
class MCPToolResult:
    """Normalized result returned from an MCP tool call."""

    content: str
    is_error: bool = False
    raw: Any = None

    def to_text(self) -> str:
        if self.is_error:
            return f"MCP tool error: {self.content}"
        return self.content


@runtime_checkable
class MCPClientProtocol(Protocol):
    """Minimal client contract required by EasyAgent MCP tools."""

    async def list_tools(self) -> list[MCPToolInfo]:
        ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        ...

    async def close(self) -> None:
        ...


class MCPError(Exception):
    """Base MCP integration error."""


class MCPConnectionError(MCPError):
    """Raised when an MCP server cannot be reached."""


class MCPToolError(MCPError):
    """Raised when MCP tool discovery or execution fails."""


def normalize_mcp_result(value: Any) -> str:
    """Convert FastMCP/MCP results into text suitable for tool messages."""

    if value is None:
        return ""

    structured = (
        getattr(value, "data", None)
        or getattr(value, "structuredContent", None)
        or getattr(value, "structured_content", None)
    )
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, default=str)

    content = getattr(value, "content", None)
    if content is not None:
        return normalize_mcp_result(content)

    if isinstance(value, str):
        return value

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, list):
        return "\n".join(
            part for item in value
            if (part := normalize_mcp_content_block(item))
        )

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)

    return str(value)


def normalize_mcp_content_block(block: Any) -> str:
    """Best-effort extraction for MCP content blocks."""

    block_type = getattr(block, "type", None)
    if block_type is None and isinstance(block, dict):
        block_type = block.get("type")

    if block_type == "text":
        return str(
            getattr(block, "text", None)
            or (block.get("text", "") if isinstance(block, dict) else "")
        )

    if block_type == "image":
        return "[image]"

    if block_type == "resource":
        resource = getattr(block, "resource", None)
        if resource is None and isinstance(block, dict):
            resource = block.get("resource")
        return normalize_mcp_result(resource)

    if isinstance(block, dict):
        return json.dumps(block, ensure_ascii=False, default=str)

    return str(block)


def _as_schema(value: Any) -> dict[str, Any]:
    data = _as_dict(value)
    if not data:
        return {"type": "object", "properties": {}}
    return data


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(exclude_none=True))
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        return dict(dict_method(exclude_none=True))
    return {}


def _extract_fastmcp_tags(meta: dict[str, Any]) -> set[str]:
    fastmcp_meta = meta.get("_fastmcp")
    if not isinstance(fastmcp_meta, dict):
        return set()
    tags = fastmcp_meta.get("tags") or []
    return {str(tag) for tag in tags}
