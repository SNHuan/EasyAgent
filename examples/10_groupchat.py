"""第 10 层：groupchat —— Reactive 轮次 + 自动路由。

09 的 chatroom 是**人**写 if/else 决定路由。这一层是它的对偶：
由 Reactive Schedule 根据最近一条 Speak 的 ``to`` 字段决定谁下一个说。

``groupchat`` preset = ConversationWorld + Reactive + UntilIdle + MaxTicks。
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
    groupchat,
)
from easyagent.events import EventBus, MessageEvent


def make(model: LiteLLMModel, name: str, system_prompt: str) -> LLMEntity:
    return LLMEntity(
        name,
        ReactAgent(
            model=model,
            name=name,
            system_prompt=system_prompt,
            max_iterations=2,
        ),
    )


def make_live_bus() -> EventBus:
    bus = EventBus()

    def on_message(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"[{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_message)
    return bus


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    coordinator = make(
        model, "coordinator",
        "你是协调员。看完用户问题，从 [planner, finance] 中选一位最合适的回答者。"
        "回复时**用 [@planner] 或 [@finance] 开头**，然后写一句问他的具体问题。",
    )
    planner = make(
        model, "planner",
        "你是行程规划专家。看到 [@planner] 时回答关于行程的问题。一句话。",
    )
    finance = make(
        model, "finance",
        "你是财务专家。看到 [@finance] 时回答关于预算的问题。一句话。",
    )

    result = await groupchat(
        [coordinator, planner, finance],
        seed="周末团建去三亚两天，预算 2000，有什么建议？",
        max_rounds=4,
        bus=make_live_bus(),
    )

    speech = result.last_speech
    if speech:
        print(f"\nfinal: {speech}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 你只提供 seed，后面的传棒完全由 Reactive Schedule 根据消息的
    #    to 字段决定——LLM 通过 @ 表达意图；
    # 2. chatroom = 人决定路由，groupchat = LLM 决定路由；
    # 3. 它们用同一组 World/Schedule/Runtime 组件，只是配置不同。


if __name__ == "__main__":
    asyncio.run(main())
