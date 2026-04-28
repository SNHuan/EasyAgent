"""第 09 层：chatroom —— 用户在循环里写 if/else 决定下一棒。

08 的 sequential 顺序写死在列表里。但很多时候你需要根据中间结果决定
下一步：审稿员说"通过"就直接发布，"需要修改"才送去改稿。

``chatroom`` 返回一个 ``ManualSession``，在 ``async with`` 块内通过
``await room.<name>()`` 调任何成员。每个成员的回复自动进入共享 World，
后续成员能看到上下文。用普通 Python if/else 决定下一棒。
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
    chatroom,
)
from easyagent.events import EventBus, MessageEvent


def make(model: LiteLLMModel, name: str, system_prompt: str) -> LLMEntity:
    return LLMEntity(
        name,
        ReactAgent(
            model=model,
            name=name,
            system_prompt=system_prompt,
            max_iterations=2,
        ),
    )


def make_live_bus() -> EventBus:
    bus = EventBus()

    def on_message(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"[{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_message)
    return bus


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    drafter = make(
        model, "drafter",
        "你是文案。写一句 20 字以内的产品宣传语，给 EasyAgent 这个开源框架。",
    )
    critic = make(
        model, "critic",
        "你是审稿。读完文案后**只**回复「通过」或「需要修改」两个词之一。"
        "不要解释，不要其他字。",
    )
    fixer = make(
        model, "fixer",
        "你是改稿员。重写文案使其更精炼，20 字以内。",
    )
    publisher = make(
        model, "publisher",
        "你是发布员。原样转发文案，前面加「最终版：」三个字。",
    )

    async with chatroom(
        [drafter, critic, fixer, publisher],
        announcement="主题：给开源 multi-agent 框架 EasyAgent 写一句宣传语。",
        bus=make_live_bus(),
    ) as room:
        await room.drafter()
        verdict = await room.critic()

        if verdict and "通过" in verdict:
            print("\n→ critic 通过，直接发布")
            await room.publisher()
        else:
            print("\n→ critic 要求改稿，先 fixer 后 publisher")
            await room.fixer()
            await room.publisher()

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 每个成员的回复自动进入 ConversationWorld——后续成员看得到；
    # 2. 路由由你（人）决定；下一层 (10) 演示 LLM 自己决定路由。


if __name__ == "__main__":
    asyncio.run(main())
