"""第 10 层：切换 Runtime 调度策略。

到这一层你已经会用默认 SequentialRuntime / ShuffledRuntime。它们的差别
只是 ``schedule_policy``：

  Sequential —— 每个 session 一批，按注册顺序，前者输出对后者可见
  Parallel   —— 一批跑全部 session，同 tick 内互不见
  Shuffled   —— 每个 session 一批，顺序随机

本例展示用 ``TickDriven`` step_policy + ``Shuffled`` schedule_policy 的
组合：每 tick 唤醒所有 agent 让它们自己决定要不要说话。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import AgentSession, MessageEvent
from easyagent.agent.base import BaseAgent
from easyagent.events.base import BaseEvent
from easyagent.runtime import ShuffledRuntime, StopAfterTicks, TickDriven


class HeartbeatSession(AgentSession):
    async def on_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        # TickDriven 每一轮都会唤醒所有 Agent。
        return [MessageEvent(
            sender=self.session_id,
            to="*",
            content=f"第 {self.metadata.get('tick')} 轮",
        )]


class HeartbeatAgent(BaseAgent):
    session_class = HeartbeatSession

    def __init__(self, name: str):
        self.name = name

    async def run(self, user_input, *, session=None) -> str:
        return f"{self.name}: {user_input}"


async def main() -> None:
    runtime = ShuffledRuntime(
        agents={"a": HeartbeatAgent("a"), "b": HeartbeatAgent("b")},
        step_policy=TickDriven(),
        stop_policy=StopAfterTicks(max_ticks=2),
    )

    # 订阅 bus 让消息边产生边打印（配合 runtime 的 tick / schedule 日志一起看）。
    def on_message(m: MessageEvent) -> None:
        target = "所有人" if m.is_broadcast else "&".join(sorted(m.to))
        print(f"[{m.sender} -> {target}] {m.content}")

    runtime.bus.subscribe(MessageEvent, on_message)
    await runtime.run()


if __name__ == "__main__":
    asyncio.run(main())
