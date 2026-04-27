"""第 06 层：第一个 Runtime —— Pipeline。

Runtime 是「把多个 agent 串起来」的容器。最直接的串法是 **pipeline**：
A 处理完调一个 ``end`` 工具把结果交给 B，B 处理完再交给 C，最后一个
agent 给出最终答案。

PipelineRuntime 的关键设计：
  • 每个 agent 跑自己的 ReAct 循环 —— 想用多少工具、想思考多久都自己决定
  • 非末位 agent 自动获得一个内置 ``end(data=...)`` 工具
  • 调 ``end`` = 「这一棒我做完了，把 data 交给下一棒」，当前 ReAct 立即终止
  • 末位 agent 没有 ``end`` 工具，他的 final answer 就是 pipeline 的结果

这是认识 Runtime 的第一站 —— 控制权由 agent 自己掌握，框架只提供
「下一棒是谁」的连接。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, MessageEvent, ReactAgent
from easyagent.runtime import PipelineRuntime


async def main() -> None:
    model = LiteLLMModel("gpt-4o-mini")

    researcher = ReactAgent(
        model=model,
        name="researcher",
        max_iterations=4,
        system_prompt=(
            "你是研究助手。任务：阅读用户输入、整理出 2-3 条要点。"
            "整理完成后调用 `end` 工具，把要点作为 data 传给下一棒（写作者）。"
            "不要自己写最终内容，只做要点整理。"
        ),
    )

    writer = ReactAgent(
        model=model,
        name="writer",
        max_iterations=4,
        system_prompt=(
            "你是写作助手。基于上一棒研究员给你的要点，写一段不超过 80 字"
            "的简短文字给用户。"
        ),
    )

    pipeline = PipelineRuntime([researcher, writer])
    print(f"chain: {pipeline.chain}")

    # 订阅 bus 让每一棒的输出立刻打印（配合 runtime 的 step 日志一起看）。
    def on_message(m: MessageEvent) -> None:
        print(f"[{m.sender}] {m.content}")

    pipeline.bus.subscribe(MessageEvent, on_message)

    await pipeline.run("介绍一下月球。")


if __name__ == "__main__":
    asyncio.run(main())
