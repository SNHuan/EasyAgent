"""第 02 层：引入 Memory 和 Context。

Memory 保存对话历史；Context 决定每一轮把哪部分历史发给模型。

每次 ``agent.run(...)`` 默认会新建一个 session（带自己独立的 memory），
所以两次 ``run`` 之间默认不记得彼此。要让 agent 跨多轮记住历史，
显式复用同一个 session：

    session = agent.create_session()
    await agent.run("...", session=session)
    await agent.run("...", session=session)   # ← memory 累积
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import Agent, LiteLLMModel
from easyagent.context import SlidingWindowContext


async def main() -> None:
    agent = Agent(
        model=LiteLLMModel("gpt-4o-mini"),
        context=SlidingWindowContext(max_messages=10),
        system_prompt="记住用户提到的偏好。",
    )

    # ── 默认：两次独立 run，互不记得 ─────────────────────────────────
    print("=== 默认：两次独立 run ===")
    r1 = await agent.run("我最喜欢的编辑器是 VS Code。")
    print("[run 1]", r1.final_output)

    r2 = await agent.run("我刚才提到的编辑器是什么？")
    print("[run 2]", r2.final_output)   # 答不出来——这是新 session

    # ── 复用同一个 session：memory 跨 run 累积 ───────────────────────
    print("\n=== 复用 session：memory 跨 run 累积 ===")
    session = agent.create_session()

    r1 = await agent.run("我最喜欢的编辑器是 VS Code。", session=session)
    print("[run 1]", r1.final_output)

    r2 = await agent.run("我喜欢用啥编辑器来着", session=session)
    print("[run 2]", r2.final_output)   # 答 VS Code


if __name__ == "__main__":
    asyncio.run(main())
