"""第 08 层：sequential —— 让 N 个 Entity 按顺序说话。

07 你看过手动搭 World+Schedule 驱动两个 Entity。当 Entity 只有 2-3 个、
顺序固定时这没问题；多了之后用户就会想要：

    result = await sequential([e1, e2, e3], "...")

``sequential`` 是第一个 preset：PipelineWorld + TakeTurns，每位严格说
一次，后续 Entity 能看到前面所有人的输出。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import (
    LiteLLMModel,
    ReactAgent,
    LLMEntity,
    sequential,
)
from easyagent.events import (
    EventBus,
    MessageEvent,
)
from easyagent.tool.web.serper import SerperSearch


def make(model: LiteLLMModel, name: str, system_prompt: str) -> LLMEntity:
    agent = ReactAgent(
        model=model,
        name=name,
        system_prompt=system_prompt,
        max_iterations=2,
    )
    agent.add_tool(SerperSearch())
    return LLMEntity(name, agent)


def make_live_bus() -> EventBus:
    bus = EventBus()

    def on_msg(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"[{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_msg)
    return bus


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    researcher = make(
        model, "researcher",
        "你是研究员。给出 2 条与用户问题相关的事实。",
    )
    drafter = make(
        model, "drafter",
        "你是起草员。基于研究员给的事实写一段 30 字以内的草稿。",
    )
    polisher = make(
        model, "polisher",
        "你是润色员。把草稿改得更口语化，30 字以内。",
    )

    result = await sequential(
        [researcher, drafter, polisher],
        "推荐一种适合周末做的运动",
        bus=make_live_bus(),
    )

    speech = result.last_speech
    if speech:
        print(f"\nfinal: {speech}")
    else:
        print("(全部沉默，没有输出)")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 一行 preset 搞定"按顺序调用 N 次"。
    # 2. PipelineWorld 保证 polisher 只看到 drafter 的输出（不是 researcher
    #    的原话），实现干净的接力。
    # 3. result.speeches() 可以拿到所有人的发言列表。


if __name__ == "__main__":
    asyncio.run(main())
