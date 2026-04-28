"""第 13 层：shared_state —— 不通过消息也能协作。

到 12 为止所有协作都是**对话**：成员通过 Speak action 互相影响。但很多
真实协作不是对话——共编一份文档、投票、累积评分、等待外部信号。

``SharedState`` + ``StatefulWorld`` 提供第二种协作原语：版本化的并发安全
KV。Entity 通过 ``SetState`` action 写入，``StateSlice`` 在 perception
里读取。配合 ``UntilPredicate`` 可以在消息流为空时也能停止。

这一层的核心证据：跑完后 shared 上有值，但 Entity 之间没有 Speak。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import (
    MaxTicks,
    Perception,
    RoundRobin,
    Runtime,
    SetState,
    SharedState,
    UntilPredicate,
)
from easyagent.worlds.stateful import StateChangedEvent, StatefulWorld
from easyagent.worlds.conversation import ConversationWorld
from easyagent.events import EventBus, MessageEvent


# 非 LLM 的 Entity——直接操作黑板，故意不发 Speak。

class WriterEntity:
    def __init__(self) -> None:
        self._id = "writer"

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> SetState | None:
        from easyagent.core.types import StateSlice
        state_slice = perception.of_type(StateSlice)
        if state_slice and any(k == "plan" for k, _ in state_slice.snapshot):
            return None
        return SetState(key="plan", value="晨跑 + 早午餐 + 看展")


class ReaderEntity:
    def __init__(self, shared: SharedState) -> None:
        self._id = "reader"
        self._shared = shared

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> SetState | None:
        from easyagent.core.types import StateSlice
        state_slice = perception.of_type(StateSlice)
        if state_slice:
            plan = dict(state_slice.snapshot).get("plan")
            if plan and not self._shared.has("review"):
                return SetState(key="review", value=f"通过：{plan}")
        return None


async def main() -> None:
    bus = EventBus()
    bus_messages: list[MessageEvent] = []
    bus.subscribe(MessageEvent, lambda m: bus_messages.append(m))

    def on_state(e: StateChangedEvent) -> None:
        print(f"[shared:{e.key} v{e.version} by {e.producer}] {e.value!r}")

    bus.subscribe(StateChangedEvent, on_state)

    shared = SharedState()
    shared.attach_bus(bus)

    inner_world = ConversationWorld()
    world = StatefulWorld(inner_world, shared)

    schedule = MaxTicks(
        inner=UntilPredicate(
            inner=RoundRobin(ids=["writer", "reader"]),
            predicate=lambda state: shared.has("review"),
        ),
        n=6,
    )

    writer = WriterEntity()
    reader = ReaderEntity(shared)

    rt = Runtime(
        world=world,
        entities={"writer": writer, "reader": reader},
        schedule=schedule,
        bus=bus,
    )

    await rt.run("协作产出周末计划")

    print(f"\nshared['plan']:   {shared.get('plan')!r}")
    print(f"shared['review']: {shared.get('review')!r}")

    inter = [m for m in bus_messages if m.sender in ("writer", "reader")]
    print(f"\nbus 上 writer/reader 互发的消息数: {len(inter)}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 协作完成了——shared 上两个 key 都有值；
    # 2. 但 bus 上 writer/reader 之间零条 MessageEvent；
    # 3. UntilPredicate 让 runtime 在黑板满足条件时停下；
    # 4. 真实场景把 shared 暴露给 LLM 用工具调用读写即可。


if __name__ == "__main__":
    asyncio.run(main())
