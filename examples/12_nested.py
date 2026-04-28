"""第 12 层：nested —— TeamEntity 实现递归嵌套。

到这里你已经会用 sequential / chatroom / groupchat / debate。它们都
返回 RuntimeResult——和单个 Entity 的输出形态一致。

``TeamEntity`` 把一个完整的 Runtime 包装成单个 Entity，所以任何
Runtime 都可以嵌进另一个 Runtime 当一棒。

下面演示 sequential 套 debate：
    planner → debate_team → writer
                  │
                  └── 内部：alice 和 bob 多轮争论，judge 仲裁

writer 只看到 debate_team 的一句结论，看不到 alice/bob 的原话——
这就是 TeamEntity 提供的封装边界。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import (
    ConversationWorld,
    LiteLLMModel,
    MaxTicks,
    ReactAgent,
    RoundRobin,
    Runtime,
    LLMEntity,
    TeamEntity,
    sequential,
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


def make_live_bus(label: str) -> EventBus:
    bus = EventBus()

    def on_message(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"{label} [{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_message)
    return bus


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    inner_bus = make_live_bus(label="  in")
    outer_bus = make_live_bus(label="OUT")

    # ── 内层：debate Runtime ───────────────────────────────────────────
    alice = make(model, "alice", "你坚持周边短途团建，强调省钱。一句话。")
    bob   = make(model, "bob",   "你坚持城市内 city walk，强调体验。一句话。")
    judge = make(model, "judge", "用一句话给出综合建议，平衡双方。")

    debate_world = ConversationWorld()
    debate_schedule = MaxTicks(inner=RoundRobin(ids=["alice", "bob"]), n=4)
    debate_runtime = Runtime(
        world=debate_world,
        entities={"alice": alice, "bob": bob},
        schedule=debate_schedule,
        bus=inner_bus,
    )

    # TeamEntity: 整个 debate runtime 当成一个 Entity
    debate_team = TeamEntity("debate_team", debate_runtime)

    # ── 外层成员 ───────────────────────────────────────────────────────
    planner = make(
        model, "planner",
        "你把用户问题改写为一句更具体的征求意见的表述（一句话）。",
    )
    writer = make(
        model, "writer",
        "把上一棒给你的建议改写成 2 句话给用户的友好回复。",
    )

    # ── 嵌套 —— debate_team 在这里就像一个普通 Entity ─────────────────
    result = await sequential(
        [planner, debate_team, writer],
        "周末团建怎么安排？",
        bus=outer_bus,
    )

    answer = result.last_speech
    if answer:
        print(f"\nanswer: {answer}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # writer 只看到 debate_team 的一句输出，看不到 alice/bob 的原话。
    # TeamEntity 把 Runtime 封装成 Entity，实现了干净的嵌套边界。


if __name__ == "__main__":
    asyncio.run(main())
