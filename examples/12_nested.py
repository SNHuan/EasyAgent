"""第 12 层：nested —— Orchestrator 自己也是 Talker。

到这里你已经会用 sequential / chatroom / groupchat / debate。它们都
返回一条 ChatMessage——和单个 Talker 的输出**形态完全一样**。

这意味着：**任何 Orchestrator 都可以塞进另一个 Orchestrator 当一棒**。

下面演示 sequential 套 debate：

    planner → debate_team → writer
                  │
                  └── 内部：alice 和 bob 多轮争论，judge 仲裁

写法上 ``debate_team`` 就是一个 ``Orchestrator(...)``——把它当成普通
Talker 放进 ``sequential([planner, debate_team, writer], ...)`` 即可。

11 层埋的伏笔在这里收：``ByJudge`` 让 debate_team 对外只暴露 judge 的
**一句**结论，writer 看不到 alice/bob 的争论原话。这是嵌套场景的核心
要求——**封装边界**：内层细节不外泄。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent
from easyagent.chat import Identity, LLMTalker, Orchestrator, sequential
from easyagent.chat.strategies import (
    Broadcast,
    ByJudge,
    MaxRounds,
    RoundRobin,
)
from easyagent.events import EventBus, MessageEvent


def make(model: LiteLLMModel, name: str, system_prompt: str) -> LLMTalker:
    return LLMTalker(
        ReactAgent(
            model=model,
            name=name,
            system_prompt=system_prompt,
            max_iterations=2,
        ),
    )


def make_live_bus(label: str) -> EventBus:
    """Subscribe a printer with a layer label, so we can see which bus
    each message came from."""
    bus = EventBus()

    def on_message(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"{label} [{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_message)
    return bus


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    # 两个独立的 bus，让你看清"封装边界"是怎么把内层细节挡住的：
    # inner_bus 看到 alice/bob/judge 的全过程；
    # outer_bus 只看到 planner / debate_team / writer 三条。
    inner_bus = make_live_bus(label="  in")
    outer_bus = make_live_bus(label="OUT")

    # ── 内层成员 ───────────────────────────────────────────────────────
    alice = make(model, "alice", "你坚持周边短途团建，强调省钱。一句话。")
    bob   = make(model, "bob",   "你坚持城市内 city walk，强调体验。一句话。")
    judge = make(model, "judge", "用一句话给出综合建议，平衡双方。")

    # ── 把 debate 团搭成一个 Orchestrator —— 它就是 Talker ─────────────
    # ``debate`` preset 也能干这件事；这里手搭 Orchestrator 是为了让你
    # 看清"preset = Orchestrator + 预选 strategy"的关系。
    debate_team = Orchestrator(
        members={"alice": alice, "bob": bob},
        routing=Broadcast(),
        turn_taking=RoundRobin(order=["alice", "bob"]),
        stop=MaxRounds(2),                  # 每人 2 轮 = 共 4 轮
        summarize=ByJudge(judge=judge),     # ★ 关键：对外只发 judge 的话
        identity=Identity("debate_team"),
        bus=inner_bus,                      # 内层事件只进 inner_bus
    )

    # ── 外层成员 ───────────────────────────────────────────────────────
    planner = make(
        model, "planner",
        "你把用户问题改写为一句更具体的征求意见的表述（一句话）。",
    )
    writer = make(
        model, "writer",
        "把上一棒给你的建议改写成 2 句话给用户的友好回复。",
    )

    # ── 嵌套 —— debate_team 在这里**就像**一个普通 Talker ─────────────
    answer = await sequential(
        [planner, debate_team, writer],
        "周末团建怎么安排？",
        bus=outer_bus,                      # 外层只看到 3 条消息：planner、debate_team、writer
    )
    if answer is not None:
        print(f"\nanswer: {answer.text}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # writer 的 memory 里**只**有一条来自 'debate_team' 的消息，
    # **没有** alice/bob 的原话。为什么重要：
    #
    #   不封装：内层 4 轮争论 → 外层 writer 看到 4+1=5 条上游消息，
    #           prompt 被污染，写不出干净的回复；
    #   封装好：内层 4 轮争论 → 外层 writer 只看到 judge 的 1 句结论。
    #
    # ``summarize`` 策略就是在每个 Orchestrator 上画的"封装边界"。


if __name__ == "__main__":
    asyncio.run(main())
