"""第 11 层：通过 FastMCP 接入 MCP 工具。

安装可选依赖：

    pip install "easy-agent-sdk[mcp]"

本例使用 FastMCP 官方推荐的 in-memory transport，实际项目里也可以把
``MCPToolset.from_fastmcp(...)`` 的参数换成 ``"./server.py"``、HTTP URL，
或 FastMCP 兼容的 ``{"mcpServers": {...}}`` 配置字典。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, MCPToolset, ReactAgent


mcp = FastMCP("Demo MCP Server")


@mcp.tool
def greet(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {name}!"


async def main() -> None:
    tools = await MCPToolset.from_fastmcp(mcp).load_tools()

    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        tools=tools,
        max_iterations=5,
    )

    result = await agent.run("请调用 MCP 工具 greet 问候 Ada。")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
