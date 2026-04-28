"""第 13 层：shared_state —— 不通过消息也能协作。

到 12 为止所有协作都是**对话**：成员通过 ChatMessage 互相影响。但很多
真实协作不是对话——共编一份文档、投票、累积评分、等待外部信号。这种
场景把状态硬塞进 ChatMessage.metadata 会让 prompt 工程变得很别扭。

``SharedState`` 是 chat 层提供的**第二种协作原语**：版本化的并发安全
KV，支持订阅和异步等待。配合 ``OnSharedKey`` 停止条件，可以让一个
Orchestrator 在 message bus **完全为空**的情况下也能协作并停止。

这一层的核心证据：跑完之后看输出会发现
  - shared['plan'] / shared['review'] 都有值（说明协作完成）；
  - 但 bus 上 writer/reader **互相之间一条消息都没有**。

把"协作"从"对话"中剥离出来，是其他 12 层都做不到的形态。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent.chat import (
    ChatMessage,
    Identity,
    Orchestrator,
    SharedState,
    StateChangedEvent,
)
from easyagent.chat.strategies import (
    Broadcast,
    LastMessage,
    OnSharedKey,
    RoundRobin,
)
from easyagent.events import EventBus, MessageEvent


# 真实场景下应该写 PutStateTool / GetStateTool 喂给 ReactAgent。这里为了
# 让 example 短小，用两个非 LLM 的 Talker 直接演示黑板交互——它们故意
# 返回 ``None``（沉默），所以**完全不在消息流里发声**。
class WriterTalker:
    """读到任何 prompt 就把一份计划写到黑板上。"""

    def __init__(self, shared: SharedState):
        self.identity = Identity("writer")
        self._shared = shared

    async def __call__(self, msg: ChatMessage | None = None, *, channel: str = "default"):
        self._shared.put("plan", "晨跑 + 早午餐 + 看展", producer="writer")
        return None  # 故意沉默：只动黑板，不发消息

    async def observe(self, msg: ChatMessage) -> None: ...
    async def aclose(self) -> None: ...


class ReaderTalker:
    """从黑板上读 plan，写一条 review 回去。"""

    def __init__(self, shared: SharedState):
        self.identity = Identity("reader")
        self._shared = shared

    async def __call__(self, msg: ChatMessage | None = None, *, channel: str = "default"):
        plan = self._shared.get("plan")
        self._shared.put("review", f"通过：{plan}", producer="reader")
        return None

    async def observe(self, msg: ChatMessage) -> None: ...
    async def aclose(self) -> None: ...


async def main() -> None:
    bus = EventBus()
    bus_messages: list[MessageEvent] = []
    bus.subscribe(MessageEvent, lambda m: bus_messages.append(m))

    # ── 实时打印黑板写入 ─────────────────────────────────────────────────
    # 与其他 example 不同：这里的"实时"看的是 StateChangedEvent —— 因为
    # 协作走的是黑板，不是消息流。每次 ``shared.put(key, value)`` 都会
    # 产生一条 StateChangedEvent。
    def on_state(e: StateChangedEvent) -> None:
        print(f"[shared:{e.key} v{e.version} by {e.producer}] {e.value!r}")

    bus.subscribe(StateChangedEvent, on_state)

    # 同时订阅 MessageEvent 是为了**证明它一条都没有**——本 example 的核心
    # 论点就是消息流静默而协作完成。
    def on_message(m: MessageEvent) -> None:
        print(f"[msg from {m.sender}] {m.content}")    # 不该被触发

    bus.subscribe(MessageEvent, on_message)

    shared = SharedState()
    shared.attach_bus(bus)   # 黑板写操作也会发 StateChangedEvent 上 bus

    workshop = Orchestrator(
        members={
            "writer": WriterTalker(shared),
            "reader": ReaderTalker(shared),
        },
        routing=Broadcast(),
        turn_taking=RoundRobin(order=["writer", "reader"]),
        stop=OnSharedKey("review"),    # 黑板上 review 出现就停
        summarize=LastMessage(),       # 没消息 → 返回 None
        shared_state=shared,
        bus=bus,
        identity=Identity("workshop"),
    )

    out = await workshop("协作产出周末计划")
    print(f"\nout (应为 None，因为成员都沉默): {out}")
    print(f"shared['plan']:   {shared.get('plan')!r}")
    print(f"shared['review']: {shared.get('review')!r}")

    inter = [m for m in bus_messages if m.sender in ("writer", "reader")]
    print(f"\nbus 上 writer/reader 互发的 ChatMessage 数: {len(inter)}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 协作**完成了**——shared 上两个 key 都被写了；
    # 2. 但 bus 上 writer→reader / reader→writer 的消息数 = 0；
    # 3. ``OnSharedKey`` 让 orchestrator 在 bus 静默的情况下也能停下；
    # 4. 真实场景把 shared 暴露给 LLM 用工具调用读写即可——这种"对话+
    #    黑板"混用是 chat 层最强的协作模式。


if __name__ == "__main__":
    asyncio.run(main())
