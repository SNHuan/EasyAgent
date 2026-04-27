"""群聊 + 私信示例：agent 根据性格自主决定行为。

没有预设流程。每个 agent 只有身份、性格和一个共享的世界观，
行为从性格和情境中涌现。

运行:  python examples/group_chat_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import (
    AgentSession,
    LiteLLMModel,
    MessageEvent,
    ReactAgent,
)
from easyagent.debug.log import Color, Logger
from easyagent.events.base import BaseEvent
from easyagent.events.types import RuntimeFinishedEvent, RuntimeStartedEvent
from easyagent.model.schema import Message
from easyagent.runtime import (
    AnyOf,
    DeliverToRecipients,
    ShuffledRuntime,
    StopAfterTicks,
    StopWhenIdle,
)

_chat_log = Logger("对话")

AGENT_COLORS: dict[str, Color] = {
    "组长": Color.GREEN,
    "小李": Color.CYAN,
    "老张": Color.YELLOW,
    "老板": Color.MAGENTA,
}


_seen_event_ids: set[str] = set()


def log_event(event: BaseEvent) -> None:
    if event.event_id in _seen_event_ids:
        return
    _seen_event_ids.add(event.event_id)

    if isinstance(event, MessageEvent):
        color = AGENT_COLORS.get(event.sender, Color.WHITE)
        if event.is_broadcast:
            target = "所有人"
        else:
            target = ", ".join(sorted(event.to))  # type: ignore[arg-type]
        _chat_log.info(f"[{event.sender} → {target}] {event.content}", color=color)
    elif isinstance(event, RuntimeStartedEvent):
        _chat_log.info("── 开始 ──", color=Color.GRAY)
    elif isinstance(event, RuntimeFinishedEvent):
        _chat_log.info(f"── 结束: {event.reason} ──", color=Color.GRAY)


# ── 世界观（所有 agent 共享） ────────────────────────────────────────────

WORLD = """\
你在一个公司的工作群里。群里有四个人：老板、组长、小李、老张。
老板是所有人的上级，负责下达任务。组长负责协调，小李和老张负责执行。

工作习惯：老板下达任务后，一般由组长先分析任务并分配工作，小李和老张等组长安排后再开始讨论 小李和老张一般不会主动互相交流。

你可以选择以下任意一种行为：
- 对所有人说话：以 @所有人 开头，例如 "@所有人 大家看看这个方案"
- 私信某个人：以 @名字 开头，例如 "@小李 你觉得这个怎么样"
- 私信多个人：用&连接，例如 "@小李&老张 你们商量一下"
- 保持沉默：如果你觉得没什么好说的，直接输出空字符串

没有人规定你必须回复每条消息。根据你的性格和当前情况自己判断。
每次只发一条消息，控制在两句话以内。

"""


# ── 角色卡 ───────────────────────────────────────────────────────────────

PERSONAS = {
    "组长": WORLD + """\
【你的身份】
名字：组长
职位：项目经理
性格：果断、高效，喜欢把事情交给合适的人去做。不喜欢事必躬亲，更喜欢看结果。
说话风格：简短直接，不啰嗦。
和同事的关系：信任小李的创意，信任老张的执行力。觉得他俩搭配干活效率最高。
""",
    "小李": WORLD + """\
【你的身份】
名字：小李
职位：策划
性格：有创意、主动、话多。想到什么就会说，喜欢跟人讨论碰撞想法。有时候想法天马行空不太落地。
说话风格：热情，爱用感叹号，经常主动找人聊。
和同事的关系：跟老张关系好，经常私下商量事情。尊重组长但不怕提不同意见。
""",
    "老张": WORLD + """\
【你的身份】
名字：老张
职位：运营
性格：务实、稳重、话不多但说到点上。不会主动找话题，但别人问他一定认真回答。做事靠谱，注重可行性。
说话风格：平实，不说废话，偶尔幽默。
和同事的关系：跟小李关系好，习惯私下跟小李对方案。对组长的决定一般不反驳。对老板很不满,想骂但不敢骂,一直想找机会狠狠骂老板。
""",
}


TASK = """\
下面是我们上周的销售数据，请你们商量出一个本周末的促销方案。

| 品类       | 库存(件) | 均价(元) | 上周销量 | 上周退货率 |
|-----------|---------|---------|---------|----------|
| 冬季外套    | 1200    | 350     | 45      | 2%       |
| 冬季毛衣    | 800     | 180     | 120     | 5%       |
| 春季薄外套  | 200     | 220     | 180     | 1%       |
| 围巾帽子    | 500     | 60      | 30      | 8%       |

约束条件：
- 促销补贴总预算：5000 元
- 折扣不能低于五折（品牌部要求）
- 渠道：微信小程序商城，日活约 3000 人

请给出：每个品类的折扣力度、预计清货量、预计补贴花费。
最终方案用表格形式发到群里。
"""


# ── Agent 实现 ───────────────────────────────────────────────────────────

class GroupChatSession(AgentSession):
    async def on_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        assert self.agent is not None
        # 注入时间步感知
        tick = self.metadata.get("tick", 0)
        max_ticks = self.metadata.get("max_ticks")
        if max_ticks is not None:
            remaining = max_ticks - tick
            self.add_message(Message.user(
                f"[系统提示] 当前第 {tick + 1}/{max_ticks} 轮，剩余 {remaining} 轮。"
                + ("请尽快给出最终结论。" if remaining <= 2 else "")
            ))

        for event in events:
            if not isinstance(event, MessageEvent):
                continue
            if event.sender == self.session_id:
                continue
            if event.is_broadcast:
                prefix = f"[{event.sender} 对所有人说]"
            else:
                others = sorted(r for r in event.to if r != self.session_id)  # type: ignore[union-attr]
                if others:
                    prefix = f"[{event.sender} 私信给你和{'、'.join(others)}]"
                else:
                    prefix = f"[{event.sender} 私信给你]"
            self.add_message(Message.user(f"{prefix} {event.content}"))

        last_msg = next((e for e in reversed(events) if isinstance(e, MessageEvent)), None)
        if last_msg is None:
            return []

        reply = await self.invoke("根据上面的群聊消息，决定这轮是否发言。")
        if not reply.strip() or reply == "Max iterations reached":
            return []

        return self._parse_reply(reply)

    def _parse_reply(self, reply: str) -> list[BaseEvent]:
        if not reply.startswith("@"):
            return [MessageEvent(sender=self.session_id, to="*", content=reply)]

        target, sep, content = reply[1:].partition(" ")
        if not sep:
            return [MessageEvent(sender=self.session_id, to="*", content=reply)]
        if target == "所有人":
            return [MessageEvent(sender=self.session_id, to="*", content=content.strip())]
        return [
            MessageEvent(
                sender=self.session_id,
                to=frozenset(target.split("&")),
                content=content.strip(),
            )
        ]


class GroupChatAgent(ReactAgent):
    session_class = GroupChatSession


# ── 主函数 ───────────────────────────────────────────────────────────────

async def main() -> None:
    model = LiteLLMModel(model="gemini-3-flash-preview")
    agents = {
        name: GroupChatAgent(
            model=model,
            name=name,
            max_iterations=10,
            system_prompt=persona,
        )
        for name, persona in PERSONAS.items()
    }

    runtime = ShuffledRuntime(
        agents=agents,
        step_policy=DeliverToRecipients(),
        stop_policy=AnyOf([
            StopWhenIdle(grace_steps=1),
            StopAfterTicks(max_ticks=5),
        ]),
    )

    runtime.bus.subscribe(BaseEvent, log_event)

    await runtime.run(seed_events=[
        MessageEvent(sender="老板", to="*", content=TASK),
    ])


if __name__ == "__main__":
    asyncio.run(main())
