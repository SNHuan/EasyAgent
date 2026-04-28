"""第 03 层：引入 ReAct 和 Tool。

ReactAgent = Agent + 工具调用 + ReAct 循环（模型 → 工具 → 模型 → ...
直到调用 ``end`` 或达到 max_iterations）。

通过 ``tools=[...]`` 把工具直接注入到 agent 的本地 ToolManager。
（``@register_tool`` 装饰器是另一种全局注册路径，配合
``tool_manager=DEFAULT_TOOL_MANAGER`` 使用，本例不需要。）
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent


class GetWeather:
    """获取城市天气。"""

    name = "get_weather"
    type = "function"
    description = "获取城市天气。"
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名",
            },
        },
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str) -> str:
        return f"{city}天气晴朗。"


async def main() -> None:
    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        tools=[GetWeather],
        max_iterations=5,
    )

    result = await agent.run("北京今天天气怎么样？")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
