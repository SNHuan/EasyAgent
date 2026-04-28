"""第 14 层（进阶）：runtime 层 —— tick 调度与自主仿真。

到 13 你已经看完了 chat 层的全部用法。**绝大多数多 agent 任务用 chat
层 5 个 preset 就够了**——这一层是给两类用户准备的进阶选项：

  (a) 你要做**社会仿真 / 自主群体**：每个 agent 异步独立跑、整个系统
      按 tick 推进、stop 由"群体何时空闲"决定；
  (b) 你需要**精细控制调度**：parallel / sequential / shuffled 谁先谁后、
      是否允许并发批次、是否每 tick 都给所有 agent 一次发言机会。

chat 层把这些抽象成"调用方写 await"的同步形态；runtime 层把它们做成
"事件总线 + 三类 policy"的异步形态——两层互不替代，**通过 RuntimeTalker
桥接**：把整个 runtime 当成一个 Talker 嵌进 chat 层；或反过来把单个
chat-layer Orchestrator 当成 runtime 的 agent。

本例展示一个**最小自主群聊**：alice/bob/carol 在每 tick 自由说话，
runtime 在所有人都沉默一轮后停止。和 09 的 chatroom 对比：
  - chatroom: 用户写 ``await room.x()`` 决定每一棒；
  - 本层:     runtime 自己 tick 推进，alice/bob/carol 各自独立"想说就说"。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import AgentSession, LiteLLMModel, MessageEvent, ReactAgent
from easyagent.events.base import BaseEvent
from easyagent.model.schema import Message
from easyagent.runtime import (
    AnyOf,
    DeliverToRecipients,
    ShuffledRuntime,
    StopAfterTicks,
    StopWhenIdle,
)


# ── 工具：让 LLM 用结构化方式发言（避免文本路由的脆弱性） ─────────────


class SendChatMessage:
    """群聊里发言的唯一渠道。

    ``messages`` 列表每项是 ``{"to": <name 或 *>, "content": <text>}``。
    一次 ``send_message`` 调用结束本 agent 这一 tick 的回合。
    """

    name = "send_message"
    type = "function"
    description = (
        "Send chat messages to other participants in this group. "
        "After this call your turn ends — say everything you want this turn "
        "in a single call. Pass an empty list to stay silent."
    )
    parameters = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "name or '*'"},
                        "content": {"type": "string"},
                    },
                    "required": ["to", "content"],
                },
            }
        },
        "required": ["messages"],
    }

    def init(self) -> None: ...

    def execute(
        self,
        messages: list[dict[str, str]] | None = None,
        *,
        session: Any,
        **kwargs: Any,
    ) -> str:
        outbox: list[tuple[str, str]] = session.loop_state.setdefault("__chat_outbox__", [])
        for item in messages or []:
            t = (item.get("to") or "").strip()
            c = (item.get("content") or "").strip()
            if t and c:
                outbox.append((t, c))
        session.loop_state["__early_exit__"] = "turn_complete"
        return f"Sent to: {', '.join(t for t, _ in outbox)}" if outbox else "Stayed silent."


# ── 自定义 session：events ↔ outbox 翻译 ─────────────────────────────────


class GroupChatSession(AgentSession):
    async def on_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        injected = 0
        for event in events:
            if not isinstance(event, MessageEvent):
                continue
            if event.sender == self.session_id:
                continue
            tag = "对所有人说" if event.is_broadcast else "私信你"
            self.add_message(Message.user(f"[{event.sender} {tag}] {event.content}"))
            injected += 1
        if injected == 0:
            return []

        # 直接驱动 step 循环（不通过 invoke，避免再注入一条假的 user msg）
        self.iteration_count = 0
        self.loop_steps.clear()
        result = await self.step()
        self.loop_steps.append(result)
        while not result.done:
            result = await self.step()
            self.loop_steps.append(result)

        outbox: list[tuple[str, str]] = self.loop_state.pop("__chat_outbox__", [])
        replies: list[BaseEvent] = []
        for target, content in outbox:
            to = "*" if target == "*" else frozenset({target})
            replies.append(MessageEvent(sender=self.session_id, to=to, content=content))
        return replies


class GroupChatAgent(ReactAgent):
    session_class = GroupChatSession

    def __init__(self, model: Any, *, name: str, system_prompt: str, **kwargs: Any):
        super().__init__(
            model,
            name=name,
            system_prompt=system_prompt,
            tools=[SendChatMessage],
            auto_end=False,    # 群聊里"结束回合"通过 send_message 表达
            **kwargs,
        )

    def build_system_prompt(self, session: AgentSession) -> str:
        # 不拼默认的 REACT_SYSTEM_PROMPT —— 那段会推模型用 ``end`` 收尾，
        # 与本场景"必须用 send_message"语义打架。
        return self._system_prompt


# ── 主程序 ────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """\
你在一个三人小群里，成员：alice、bob、carol。
通过 send_message 工具发言，不要直接输出文字回复。
每条内容保持一句话以内。"""


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")
    runtime = ShuffledRuntime(
        agents={
            "alice": GroupChatAgent(model=model, name="alice", system_prompt=f"你是 alice。\n{SYSTEM_PROMPT}"),
            "bob":   GroupChatAgent(model=model, name="bob",   system_prompt=f"你是 bob。\n{SYSTEM_PROMPT}"),
            "carol": GroupChatAgent(model=model, name="carol", system_prompt=f"你是 carol。\n{SYSTEM_PROMPT}"),
        },
        step_policy=DeliverToRecipients(),     # 按 msg.to 投递
        stop_policy=AnyOf([StopWhenIdle(grace_steps=1), StopAfterTicks(max_ticks=4)]),
    )

    # 订阅 bus 实时打印（和 chat 层的 EventBus 是同一个东西）
    def on_message(m: MessageEvent) -> None:
        target = "所有人" if m.is_broadcast else "&".join(sorted(m.to))
        print(f"[{m.sender} -> {target}] {m.content}")

    runtime.bus.subscribe(MessageEvent, on_message)

    seed = MessageEvent(sender="user", to="*", content="周末一起吃个饭吧？")
    await runtime.run([seed])

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 这一层做到了 chat 层做不到的事：**真正的 tick 调度**——alice/bob/
    #    carol 各自有 session，每 tick runtime 决定谁有事件可处理；
    # 2. ``ShuffledRuntime`` 让每 tick 的发言顺序随机，模拟"谁先看到群消息
    #    就谁先回复"的真实感；
    # 3. ``StopWhenIdle(grace_steps=1)`` 让群体在所有人沉默一轮后自动停下；
    # 4. **代价**：你写了 ~150 行（自定义工具 + 自定义 session + 三个
    #    policy）。如果你的需求其实是"按顺序串三个 agent"，09 的 chatroom
    #    或 08 的 sequential 五行就搞定。
    #
    # 选择标准：你需不需要 tick 调度 / stop policy / event bus 的精细
    # 控制？如果**不**需要，留在 chat 层。

if __name__ == "__main__":
    asyncio.run(main())
