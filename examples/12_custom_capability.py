"""第 12 层：自定义工具。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent, register_tool


@register_tool
class CurrentTime:
    """返回一个固定的示例时间。"""

    name = "current_time"
    type = "function"
    description = "返回一个固定的示例时间。"
    parameters = {"type": "object", "properties": {}}

    def init(self) -> None:
        pass

    def execute(self) -> str:
        return "2026-04-25 12:00:00"


async def main() -> None:
    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        tools=[CurrentTime],
        max_iterations=5,
        system_prompt="当用户询问时间时，使用 current_time 工具。",
    )

    result = await agent.run("现在几点？请使用可用工具。")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
