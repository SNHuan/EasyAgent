"""MCP integration helpers for EasyAgent."""

from easyagent.mcp.adapter import MCPToolAdapter
from easyagent.mcp.base import (
    MCPClientProtocol,
    MCPClientSource,
    MCPConnectionError,
    MCPError,
    MCPToolError,
    MCPToolInfo,
    MCPToolResult,
    normalize_mcp_content_block,
    normalize_mcp_result,
)
from easyagent.mcp.fastmcp_client import FastMCPClientAdapter
from easyagent.mcp.toolset import MCPToolset, load_mcp_tools, register_mcp_tools

__all__ = [
    "MCPClientSource",
    "MCPClientProtocol",
    "MCPError",
    "MCPConnectionError",
    "MCPToolError",
    "MCPToolInfo",
    "MCPToolResult",
    "normalize_mcp_result",
    "normalize_mcp_content_block",
    "FastMCPClientAdapter",
    "MCPToolAdapter",
    "MCPToolset",
    "load_mcp_tools",
    "register_mcp_tools",
]
