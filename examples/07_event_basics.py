"""第 07 层：Event 系统基础。

PipelineRuntime（06）够用，但只能表达「按固定顺序串起来」。
当 agent 之间是松耦合的（A 不知道 B 是谁、B 不知道 A 在干什么），
就需要一个公共的事件总线让它们通过事件通信。

下一层的 ``TickBasedRuntime`` 就是建在这个基础上。在认识它之前，
先理解事件层本身：

  1. MessageEvent —— 一个带 sender / to / content 的不可变数据
  2. EventBus     —— 一个支持发布、订阅、历史查询的总线

本例完全不出现 Agent / Runtime —— 只看事件本身长什么样。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import EventBus, MessageEvent


async def main() -> None:
    bus = EventBus()

    # 订阅者：拿到任何 MessageEvent 都打印出来。
    def on_message(event: MessageEvent) -> None:
        # to 可以是 "*"（广播）或 ({...})（私信/子群）。
        target = "*" if event.to == "*" else "&".join(sorted(event.to))
        print(f"  [{event.sender} -> {target}] {event.content}")

    bus.subscribe(MessageEvent, on_message)

    # 发布广播。
    await bus.publish(MessageEvent(sender="user", to="*", content="大家好"))

    # 发布私信：单个收件人直接传字符串。
    await bus.publish(MessageEvent(
        sender="alice",
        to="bob",
        content="只有 bob 看得到这条",
    ))

    # 发布子群消息：多个收件人用 frozenset。
    await bus.publish(MessageEvent(
        sender="alice",
        to=frozenset({"bob", "carol"}),
        content="发给 bob 和 carol",
    ))

    # EventBus 保留全部历史，可以回放或离线分析。
    print("\n=== 历史 ===")
    for event in bus.history(MessageEvent):
        target = "*" if event.to == "*" else "&".join(sorted(event.to))
        print(f"  [{event.sender} -> {target}] {event.content}")


if __name__ == "__main__":
    asyncio.run(main())
