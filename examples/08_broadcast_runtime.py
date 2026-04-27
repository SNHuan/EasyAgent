"""第 08 层：广播型 Runtime。

到 06 你看到的 PipelineRuntime 是「函数式串行」——每个 agent 都明确知道
谁是上游、谁是下游。

但有些场景里，你希望 agent 之间是**松耦合**的：「把这条消息扔到群里，
谁该回就回」。这就是 ``TickBasedRuntime`` 家族（``SequentialRuntime`` /
``ParallelRuntime`` / ``ShuffledRuntime``）的模型——基于 EventBus 的
广播 / 订阅。

模型要点（和 Pipeline 的核心区别）：
  • Runtime 是个「世界 / 事件总线」。agent 不直接调用彼此，而是发事件。
  • ``step_policy`` 决定每条事件投递给谁（``DeliverToRecipients`` 按
    ``MessageEvent.to`` 投递）。
  • ``schedule_policy`` 决定同一 tick 内多个收件人之间的执行顺序：
        Sequential = 按注册顺序串行（前者输出对后者可见）
        Parallel   = 同 tick 内并发（互不见）
        Shuffled   = 串行但顺序随机
  • ``stop_policy`` 决定何时停。

注意 ``SequentialRuntime`` 不是「pipeline」——它是「广播 + 同 tick 内串行」。
想要 pipeline 用 ``PipelineRuntime``。

本例使用最常见组合：DeliverToRecipients + Sequential。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, MessageEvent, ReactAgent
from easyagent.runtime import DeliverToRecipients, SequentialRuntime, StopAfterTicks


async def main() -> None:
    model = LiteLLMModel("gpt-4o-mini")

    runtime = SequentialRuntime(
        agents={
            "alice": ReactAgent(
                model=model,
                name="alice",
                system_prompt="你是 Alice，回复一句话。",
            ),
            "bob": ReactAgent(
                model=model,
                name="bob",
                system_prompt="你是 Bob，你喜欢在中午吃麻辣烫。",
            ),
        },
        step_policy=DeliverToRecipients(),
        stop_policy=StopAfterTicks(max_ticks=2),  # 只跑一 tick：每人各自答一次
    )

    # 订阅 bus 让消息边产生边打印（配合 runtime 的 tick / schedule 日志一起看）。
    def on_message(m: MessageEvent) -> None:
        target = "所有人" if m.is_broadcast else "&".join(sorted(m.to))
        print(f"[{m.sender} -> {target}] {m.content}")

    runtime.bus.subscribe(MessageEvent, on_message)

    # 广播 seed：alice 和 bob 都会收到、各自独立回复 user。
    seed = MessageEvent(sender="user", to="*", content="推荐一个午饭。")
    await runtime.run([seed])


if __name__ == "__main__":
    asyncio.run(main())
