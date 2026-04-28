"""第 11 层：debate —— 第三方仲裁产出结论。

08-10 的 ``sequential`` / ``chatroom`` / ``groupchat`` 容器都把"最后一条
消息"原样作为结果返回。但很多多 agent 任务里，最后说话的人**不**应该
代表最终结论——比如两个观点对立的人吵了几轮，谁说最后一句不重要，
重要的是**有第三方仲裁**给出综合结论。

``debate`` preset 解决这个：
  - ``talkers`` 轮流发言（默认 round-robin）；
  - 一个独立的 ``judge`` Talker **不参与**辩论，只在最后看完全过程后
    输出仲裁意见；
  - 容器返回的是 judge 的话，**而不是**最后一个辩手的话。

实现机制：``ByJudge`` summarize 策略。后面 12 层会展示这条机制为什么
关键——它让 debate **作为一棒**嵌进更大的 pipeline 时不会泄露内部细节。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent
from easyagent.chat import LLMTalker, debate
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

    # ── 订阅 bus 实时打印每一棒的发言 ────────────────────────────────────
    # Orchestrator 在每位成员说完之后会 publish 一条 MessageEvent；订阅它
    # 就能在 debate 跑完之前**逐句**看到 alice/bob 在说什么，而不是只看到
    # judge 最后的仲裁。
    bus = EventBus()

    def on_message(m: MessageEvent) -> None:
        target = "*" if m.to == "*" else "&".join(sorted(m.to))
        print(f"[{m.sender} → {target}] {m.content}")

    bus.subscribe(MessageEvent, on_message)

    verdict = await debate(
        [alice, bob],
        judge=judge,
        seed="周末团建：山区露营 vs 海边度假，谁更合适？",
        max_rounds=4,           # 每人最多 4 轮 → 最多 8 轮发言
        bus=bus,
    )
    if verdict is not None:
        print(f"\nverdict: {verdict.content}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. ``verdict.sender.name == 'debate'`` —— 容器对外的 sender 是
    #    容器名 ('debate')，**不是** judge 或 alice/bob 的名字；
    # 2. ``verdict.metadata['judged_by'] == 'judge'`` —— 但 metadata 里
    #    保留了真实出处便于追溯；
    # 3. judge **看到了完整 transcript** 才发言——和单纯让 alice/bob
    #    互骂不同，judge 是后置的总结者。
    #
    # 这种"内部多轮 + 外部一句"的 split 是下一层 (12) 嵌套的关键：
    # 如果不把内部争论封装起来，外层 pipeline 就会被 alice/bob 的原话
    # 污染。


if __name__ == "__main__":
    asyncio.run(main())
