"""第 09 层：定制 session.step。

到这一层，你已经知道：
  - Event 是什么（07）
  - Runtime 怎么用默认行为驱动 agent（08）

现在反过来看 SDK 内部默认 step 在做的事——它把 events 转成 user message
塞进 memory、跑一次 loop、把结果包成 MessageEvent。

如果你想加更多语义（比如把 sender 名字以更醒目的格式注入、或在路由时
解析 @xxx 选择回复对象），重写 ``AgentSession.step`` 即可。

本例演示的定制行为：
  - 给 memory 里的多 agent 消息加上「[alice 说]」前缀
  - 跳过自己发的消息（用 session_id 判断）
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import AgentSession, LiteLLMModel, MessageEvent, ReactAgent
from easyagent.events.base import BaseEvent
from easyagent.model.schema import Message
from easyagent.runtime import DeliverToRecipients, SequentialRuntime, StopAfterTicks


class GroupChatSession(AgentSession):
    """重写 on_events：把所有非自己的消息都注入 memory 并广播回复。"""

    async def on_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        # 注入：让模型看到完整的群聊历史。
        for event in events:
            if not isinstance(event, MessageEvent):
                continue
            if event.sender == self.session_id:
                continue
            self.add_message(Message.user(f"[{event.sender} 说] {event.content}"))

        # 找出本轮要回应的最后一条非自己消息。
        last = next(
            (e for e in reversed(events)
             if isinstance(e, MessageEvent) and e.sender != self.session_id),
            None,
        )
        if last is None:
            return []

        # invoke 跑一次 loop（不重新启停生命周期，因为 Runtime 已经处理了）。
        reply = await self.invoke(last.content)
        if not reply.strip():
            return []

        # 显式选择 broadcast，让所有 agent 都能看到。
        return [MessageEvent(sender=self.session_id, to="*", content=reply)]


class GroupChatAgent(ReactAgent):
    session_class = GroupChatSession  # 让 Agent 用我们这个 session 子类


async def main() -> None:
    model = LiteLLMModel("gpt-4o-mini")

    runtime = SequentialRuntime(
        agents={
            "alice": GroupChatAgent(model=model, name="alice", system_prompt="你是 Alice，回复要简短。"),
            "bob": GroupChatAgent(model=model, name="bob", system_prompt="你是 Bob，回复要简短。"),
        },
        step_policy=DeliverToRecipients(),
        stop_policy=StopAfterTicks(max_ticks=2),
    )

    # 订阅 bus 让消息边产生边打印（配合 runtime 的 tick / schedule 日志一起看）。
    def on_message(m: MessageEvent) -> None:
        target = "所有人" if m.is_broadcast else "&".join(sorted(m.to))
        print(f"[{m.sender} -> {target}] {m.content}")

    runtime.bus.subscribe(MessageEvent, on_message)

    await runtime.run([
        MessageEvent(sender="user", to="*", content="推荐一个午饭选择。")
    ])


if __name__ == "__main__":
    asyncio.run(main())
