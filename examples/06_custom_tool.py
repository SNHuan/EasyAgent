"""第 06 层：自定义工具。

03 已经看过 ReactAgent 怎么用内置工具。这一层教你怎么把自己的代码包成
一个工具喂给 ReactAgent。

定义工具只需要五个属性 + 两个方法：
  name / type / description / parameters / init() / execute()

``@register_tool`` 装饰器把它登记到全局工具表，``ReactAgent(tools=[...])``
就能引用。``parameters`` 是标准 JSON Schema —— 模型会按 schema 生成参数。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from datetime import datetime
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
        return datetime.now()


async def main() -> None:
    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        tools=[CurrentTime],
        max_iterations=5,
        system_prompt="当用户询问时间时，使用 current_time 工具。",
    )

    result = await agent.run("现在几点？")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
