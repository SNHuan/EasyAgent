"""第 12 层：从 MCP config 加载并注册工具。

这个例子展示 EasyAgent 侧推荐的 MCP 配置形态：

1. MCP server 名就是工具分类，例如 ``literature`` / ``materials``。
2. ``register_mcp_tools`` 负责从 FastMCP Client 发现工具并注册到 ToolManager。
3. AgentSession 通过 ``enabled_tools`` 决定本轮真正暴露给模型的工具。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent, ToolManager, register_mcp_tools


CONFIG_PATH = Path(__file__).with_name("mcp_config.example.json")


def load_example_mcp_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


async def main() -> None:
    os.chdir(ROOT)
    mcp_config = load_example_mcp_config()
    tool_manager = ToolManager(discover_builtin=False)

    literature_tools = await register_mcp_tools(
        tool_manager,
        mcp_config,
        servers=["literature"],
    )

    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        tool_manager=tool_manager,
        max_iterations=5,
    )

    session = agent.create_session()
    session.enabled_tools.extend(literature_tools)

    result = await agent.run(
        "搜索并总结 3 篇关于 perovskite solar cells stability 的文献。",
        session=session,
    )
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
