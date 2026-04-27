"""第 11 层：完整群聊（多 agent 涌现）。

09 之前我们直接重写 ``AgentSession.on_events`` 来手动决定回复发给谁。
这能用，但路由逻辑藏在文本解析里：模型多输出一个空格、漏一个 @、
中文标点和英文标点混用，路由就坏了。

本例采用更"工具化"的写法：

  • 给每个 agent 注入一个自定义 ``send_message`` 工具，
  • 工具参数是 ``[{"to": ..., "content": ...}, ...]`` —— 每项一个收件人，
    ``"to"`` 用具体名字（``"alice"``）或 ``"*"`` 表示广播，
  • LLM 直接选择发给谁——不用再做正则/字符串解析，
  • 调用一次 ``send_message`` 就当做"这一轮发完了"，循环结束。

所以 GroupChatSession 只负责：把消息倒进 memory → 跑一次 loop →
把 session 的"出件箱"翻译成 MessageEvent。

人机交互版（人类作为参与者实时参与）见 ``examples/group_chat_demo.py``。
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


# ── 自定义工具：让 LLM 用结构化方式发言 ─────────────────────────────────────

class SendChatMessage:
    """LLM 在群聊里发言的唯一渠道。

    参数 ``messages`` 是一个 list，每项 ``{"to": <recipient>, "content": <text>}``。
      - ``to`` 是某个成员名（如 ``"alice"``）或 ``"*"`` 表示广播；
      - 同一次调用可以包含多条，发不同内容给不同人；
      - 空 list 表示这一轮选择沉默。
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
                "description": (
                    "List of messages to send this turn. Each item routes to "
                    "one recipient. You can include multiple items to address "
                    "different participants in the same turn."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": (
                                "Recipient: a participant name (e.g. 'alice') "
                                "or '*' to broadcast to everyone."
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": "The message text.",
                        },
                    },
                    "required": ["to", "content"],
                },
            }
        },
        "required": ["messages"],
    }

    def init(self) -> None:
        pass

    def execute(
        self,
        messages: list[dict[str, str]] | None = None,
        *,
        session: Any,
        **kwargs: Any,
    ) -> str:
        outbox: list[tuple[str, str]] = session.loop_state.setdefault("__chat_outbox__", [])
        for item in messages or []:
            target = (item.get("to") or "").strip()
            content = (item.get("content") or "").strip()
            if not target or not content:
                continue
            outbox.append((target, content))
        # 一次 send_message 就是一轮发言：发完即结束。
        session.loop_state["__early_exit__"] = "turn_complete"
        if not outbox:
            return "Stayed silent this turn."
        targets = ", ".join(t for t, _ in outbox)
        return f"Sent to: {targets}"


# ── 自定义 session：把 events 喂给 loop，把 outbox 翻译成 events ─────────

class GroupChatSession(AgentSession):
    async def on_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        # 注入：把别人发的群聊内容塞进 memory，让模型有上下文。
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

        # 直接驱动 step 循环，不走 invoke()。
        # invoke() / run_session() 会强制再 add_message(Message.user(user_input))，
        # 而我们上面已经把所有需要的上下文都注入 memory 了，再塞一个假的 user
        # message 反而让模型搞不清"我该回应哪一条"。
        # 模型看到 memory 末尾是 user 消息，OpenAI 协议本身就期待 assistant 回复。
        self.iteration_count = 0
        self.loop_steps.clear()
        result = await self.step()
        self.loop_steps.append(result)
        while not result.done:
            result = await self.step()
            self.loop_steps.append(result)

        # 把 send_message 工具留在 outbox 里的内容翻译成事件。
        outbox: list[tuple[str, str]] = self.loop_state.pop("__chat_outbox__", [])
        replies: list[BaseEvent] = []
        for target, content in outbox:
            to = "*" if target == "*" else frozenset({target})
            replies.append(MessageEvent(sender=self.session_id, to=to, content=content))
        return replies


class GroupChatAgent(ReactAgent):
    session_class = GroupChatSession

    def __init__(self, model: Any, *, name: str, system_prompt: str, **kwargs: Any):
        # auto_end=False：群聊里"结束回合"只通过 send_message 表达，不要再
        # 让模型见到 end 工具。否则它会被 REACT_SYSTEM_PROMPT 里"用 end 结束
        # 任务"的规则带偏，根本不调 send_message。
        super().__init__(
            model,
            name=name,
            system_prompt=system_prompt,
            tools=[SendChatMessage],
            auto_end=False,
            **kwargs,
        )

    def build_system_prompt(self, session: AgentSession) -> str:
        # 不拼 REACT_SYSTEM_PROMPT——它的 "Completion Rules" 节明确要求用 end
        # 工具收尾，与本场景"必须用 send_message 发言"的语义直接打架。
        return self._system_prompt


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
        step_policy=DeliverToRecipients(),
        stop_policy=AnyOf([StopWhenIdle(grace_steps=1), StopAfterTicks(max_ticks=4)]),
    )

    # 订阅 bus 让消息边产生边打印（配合 runtime 的 tick / schedule 日志一起看）。
    def on_message(m: MessageEvent) -> None:
        target = "所有人" if m.is_broadcast else "&".join(sorted(m.to))
        print(f"[{m.sender} -> {target}] {m.content}")

    runtime.bus.subscribe(MessageEvent, on_message)

    seed = MessageEvent(sender="user", to="*", content="周末一起吃个饭吧？")
    await runtime.run([seed])


if __name__ == "__main__":
    asyncio.run(main())
