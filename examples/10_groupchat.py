"""第 10 层：groupchat —— 让 LLM 自己决定下一个谁说话。

09 的 chatroom 是**人**写 if/else 决定路由。这一层是它的对偶：让 LLM
**自己**在消息里 ``@`` 下一个发言者。

``ChatMessage`` 有个 ``to`` 字段——可以是 ``"*"``（广播）、单名 (``"bob"``)
或集合 (``{"alice", "bob"}``)。``groupchat`` preset 用 ``Direct`` routing
+ ``Reactive`` turn-taking：
  - 谁的名字出现在最近一条消息的 ``to`` 里，下一个就轮谁说；
  - 调用方提前**不知道**谁会被点到——这就是和 chatroom 的本质差异。

实际中 LLM 通过把名字写进文本 (``[@finance] ...``) 表达意图——下面
让 coordinator 充当"前台"，把问题路由给 planner 或 finance。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent
from easyagent.chat import ChatMessage, Identity, LLMTalker, groupchat
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


def make_live_bus() -> EventBus:
    """Subscribe a printer that fires the moment any member speaks."""
    bus = EventBus()

    def on_message(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"[{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_message)
    return bus


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    # 注：这是 demo——真实场景里"@路由"通常通过工具调用而非自由文本来
    # 实现（更稳）。这里用文本模拟够直观。
    coordinator = make(
        model, "coordinator",
        "你是协调员。看完用户问题，从 [planner, finance] 中选一位最合适的回答者。"
        "回复时**用 [@planner] 或 [@finance] 开头**，然后写一句问他的具体问题。",
    )
    planner = make(
        model, "planner",
        "你是行程规划专家。看到 [@planner] 时回答关于行程的问题。一句话。",
    )
    finance = make(
        model, "finance",
        "你是财务专家。看到 [@finance] 时回答关于预算的问题。一句话。",
    )

    gc = groupchat(
        [coordinator, planner, finance],
        routing="direct",     # 严格按 msg.to 投递
        max_rounds=4,
        bus=make_live_bus(),  # 每位发言落地立刻打印
    )

    # 用户先点 coordinator —— 注意 ``to=`` 字段直接表达「这条信发给谁」
    seed = ChatMessage(
        sender=Identity("user", role="user"),
        content="周末团建去三亚两天，预算 2000，有什么建议？",
        to="coordinator",
        role="user",
    )
    final = await gc(seed)
    if final is not None:
        print(f"\nfinal: {final.text}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 你只塞了一个 seed (to="coordinator")，后面 coordinator → planner /
    #    finance 的传棒**完全是 LLM 自己决定的**——通过它在消息里写的 @；
    # 2. 09 的 chatroom 是 manual turn-taking（你写 if/else），10 的
    #    groupchat 是 LLM-driven turn-taking（LLM 写 @）；
    # 3. 它们都用同一个 ``Orchestrator`` 实现，只是策略组合不同：
    #    chatroom = Manual + Broadcast；groupchat = Reactive + Direct。


if __name__ == "__main__":
    asyncio.run(main())
