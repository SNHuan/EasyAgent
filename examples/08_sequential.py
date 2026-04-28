"""第 08 层：sequential —— 让 N 个 Talker 按顺序说话。

07 你看过 ``await alice(msg) → await bob(msg)`` 这种**手动**串联。当
Talker 只有 2-3 个、顺序固定时这没问题；多了之后用户就会想要：

    final = await sequential([t1, t2, t3], "...")

``sequential`` 是 chat 层的第一个 preset：调用方写死顺序，每位严格说一次，
最终输出就是末位的发言。下游能看到上游全部发言（不像普通 pipeline 只能
看到上一棒）。

它就是 Orchestrator + 一组预选 strategy 的工厂——没有任何特殊机制，
只是把一种最常见的形态做成单行 API。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent
from easyagent.chat import LLMTalker, sequential
from easyagent.events import (
    EventBus,
    LLMRespondedEvent,
    MessageEvent,
    ToolCalledEvent,
    ToolResultEvent,
)
from easyagent.tool.web.serper import SerperSearch


def make(model: LiteLLMModel, name: str, system_prompt: str) -> LLMTalker:
    react_agent = ReactAgent(
            model=model,
            name=name,
            system_prompt=system_prompt,
            max_iterations=2,
        )
    react_agent.add_tool(SerperSearch())
    return LLMTalker(
        agent=react_agent
    )


def make_live_bus() -> EventBus:
    """
      MessageEvent     一条 ChatMessage 落地（一棒结束）
      LLMRespondedEvent 每次 LLM 调用回来一段内容
      ToolCalledEvent   每次工具调用
      ToolResultEvent   工具返回

    把 bus 传给 sequential/chatroom/Orchestrator 后，框架会**自动**把这个
    bus 装进每个 LLMTalker 的 session.event_bus，于是 ReactAgent 内部已经
    在发的遥测就会全部冒上来——不用任何额外接线。
    """
    bus = EventBus()

    def on_msg(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"[{m.sender} → {target}] {m.content}")

    def on_tool(m: ToolCalledEvent) -> None:
        print(f"{m.tool_name} -> {m.arguments}")

    bus.subscribe(MessageEvent, on_msg)
    bus.subscribe(ToolCalledEvent,on_tool)
    return bus


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    researcher = make(
        model, "researcher",
        "你是研究员。给出 2 条与用户问题相关的事实。",
    )
    drafter = make(
        model, "drafter",
        "你是起草员。基于研究员给的事实写一段 30 字以内的草稿。",
    )
    polisher = make(
        model, "polisher",
        "你是润色员。把草稿改得更口语化，30 字以内。",
    )

    # 把 bus 传进去，每位说完就实时打印。
    final = await sequential(
        [researcher, drafter, polisher],
        "推荐一种适合周末做的运动",
        bus=make_live_bus(),
    )

    if final is not None:
        print(f"\nfinal: {final.text}")
    else:
        print("(全部沉默，没有输出)")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. 没有写循环。preset 帮你把"按顺序调用 N 次"封装好了。
    # 2. 末位 polisher 看得到 researcher 和 drafter 的全部发言——这是
    #    sequential 的语义保证（中间所有人对所有人广播）。
    # 3. final.metadata['underlying_sender'] 会是 'polisher'，告诉你这
    #    句话**实际**出自谁。sequential 把容器名 ('sequential') 标在
    #    sender 上，但保留了 underlying 信息便于追溯。


if __name__ == "__main__":
    asyncio.run(main())
