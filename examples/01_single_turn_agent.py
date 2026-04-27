"""第 01 层：组合一个最小 Agent。

``Agent`` 是最基础的单轮对话——一次 ``run`` = 一次模型调用。
不传 ``memory`` / ``context`` 就用默认值（``InMemoryMemory`` +
``SlidingWindowContext``）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import Agent, LiteLLMModel


async def main() -> None:
    agent = Agent(
        model=LiteLLMModel("gpt-4o-mini"),
        system_prompt="你是一个简洁可靠的助手。",
    )

    result = await agent.run("什么是 Agent？")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
