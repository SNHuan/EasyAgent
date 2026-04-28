"""第 07 层：让两个 agent 互相说话。

到这一层为止你都在和**一个** agent 打交道：``await agent.run("...")``。
这一层引入第二个 agent，让它们**直接互相说话**——既不用 runtime、
也不用 event bus、也不用 policy。

核心抽象只有一个：**Talker**。
  - 用 ``LLMTalker(react_agent)`` 把现有 ReactAgent 包成 Talker；
  - Talker 的协议就是 ``await talker(msg) -> ChatMessage | None``；
  - 一个 Talker 的输出可以直接丢给另一个 Talker。

接下来从 08 起会引入 ``sequential`` / ``chatroom`` / ``groupchat`` 等糖，
但那些都建立在这一层的 Talker 协议之上。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent
from easyagent.chat import ChatMessage, Identity, LLMTalker


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    # ── 1. 把 ReactAgent 包成 Talker ───────────────────────────────────
    # ReactAgent 自身一行没改；LLMTalker 只是套了一层让它实现 Talker 协议。
    alice = LLMTalker(
        ReactAgent(
            model=model,
            name="alice",
            system_prompt="你是 alice。用一句话回答。",
            max_iterations=2,
        ),
    )
    bob = LLMTalker(
        ReactAgent(
            model=model,
            name="bob",
            system_prompt="你是 bob。用一句话回应。",
            max_iterations=2,
        ),
    )

    # ── 2. 用一条 ChatMessage 启动对话 ─────────────────────────────────
    user_msg = ChatMessage(
        sender=Identity("user", role="user"),
        content="你们觉得周末该做点什么？",
        role="user",
    )

    # ── 3. alice 说 → bob 说 —— 就是普通函数调用 ─────────────────────
    alice_says = await alice(user_msg)
    if alice_says is None:
        print("alice 选择沉默"); return
    print(f"[alice] {alice_says.text}")

    bob_says = await bob(alice_says)
    if bob_says is None:
        print("bob 选择沉默"); return
    print(f"[bob]   {bob_says.text}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # ChatMessage 自带 sender/to/channel/reply_to——下游 Talker 看到上游
    # 是谁、回复给谁、在哪个频道——这一切是数据，不是订阅器状态。
    # 整段代码没有出现 runtime / event / policy，未来 8-13 层的 preset
    # 都只是这种「直接调用」的批量糖。


if __name__ == "__main__":
    asyncio.run(main())
