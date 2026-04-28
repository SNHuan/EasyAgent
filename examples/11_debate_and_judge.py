"""第 11 层：debate —— 第三方仲裁产出结论。

08-10 的容器都把"最后一条发言"原样作为结果返回。但很多任务里最后
说话的人不代表最终结论——比如两个对立观点吵了几轮，需要第三方仲裁。

``debate`` preset 在轮次结束后调用 ``judge`` Entity 看完全过程产出
仲裁意见。``result.last_speech`` 就是 judge 的话。
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
    debate,
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


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")

    alice = make(
        model, "alice",
        "你坚持去山区露营。听到对方观点后简短反驳并强化自己的立场。一句话。",
    )
    bob = make(
        model, "bob",
        "你坚持去海边度假。听到对方观点后简短反驳并强化自己的立场。一句话。",
    )
    judge = make(
        model, "judge",
        "你是仲裁。综合双方观点，用一句话给出**结论性**建议。"
        "不要复述各方立场，直接给方案。",
    )

    bus = EventBus()

    def on_message(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"[{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_message)

    result = await debate(
        [alice, bob],
        judge=judge,
        seed="周末团建：山区露营 vs 海边度假，谁更合适？",
        max_rounds=4,
        bus=bus,
    )

    verdict = result.last_speech
    if verdict:
        print(f"\nverdict: {verdict}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. judge 不参与辩论轮次——它在所有轮结束后看完整 transcript 才发言；
    # 2. result.last_speech 是 judge 的话，不是 alice/bob 的；
    # 3. 这种"内部多轮 + 外部一句"是下一层 (12) 嵌套的关键。


if __name__ == "__main__":
    asyncio.run(main())
