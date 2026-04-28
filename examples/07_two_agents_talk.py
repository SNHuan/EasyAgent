"""第 07 层：让两个 Entity 互相说话。

到这一层为止你都在和**一个** agent 打交道：``await agent.run("...")``。
这一层引入第二个 agent，让它们通过 Entity-World-Schedule 架构互相对话。

核心抽象：
  - ``LLMEntity(id, agent)`` 把 Agent 包成 Entity；
  - Entity 的协议就是 ``async act(Perception) -> Action | None``；
  - ``ConversationWorld`` 管理对话历史，每个 Entity 看到完整上下文。

接下来从 08 起会引入 ``sequential`` / ``debate`` / ``chatroom`` 等糖，
但那些都建立在这一层的 Entity-World-Schedule 协议之上。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import (
    LiteLLMModel,
    ReactAgent,
    LLMEntity,
    ConversationWorld,
    Runtime,
    RoundRobin,
    MaxTicks,
)


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    # ── 1. 把 ReactAgent 包成 Entity ──────────────────────────────────
    alice = LLMEntity(
        "alice",
        ReactAgent(
            model=model,
            name="alice",
            system_prompt="你是 alice。用一句话回答。",
            max_iterations=2,
        ),
    )
    bob = LLMEntity(
        "bob",
        ReactAgent(
            model=model,
            name="bob",
            system_prompt="你是 bob。读了 alice 的话后用一句话回应。",
            max_iterations=2,
        ),
    )

    # ── 2. 搭 World + Schedule + Runtime ──────────────────────────────
    world = ConversationWorld()
    schedule = MaxTicks(inner=RoundRobin(ids=["alice", "bob"]), n=2)
    rt = Runtime(
        world=world,
        entities={"alice": alice, "bob": bob},
        schedule=schedule,
    )

    # ── 3. 运行 ──────────────────────────────────────────────────────
    result = await rt.run("你们觉得周末该做点什么？")

    for entity_id, speech_text in result.speeches():
        print(f"[{entity_id}] {speech_text}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # Entity + World + Schedule 三个协议正交分离：
    #   - Entity 只管"拿到 Perception 产出 Action"；
    #   - World 只管"维护状态 + 构造 Perception + 处理 Action"；
    #   - Schedule 只管"谁下一个发言"。
    # 这段代码没有出现 policy / strategy / routing，因为那些都已经
    # 分解进了 World（可见性）和 Schedule（轮次）。


if __name__ == "__main__":
    asyncio.run(main())
