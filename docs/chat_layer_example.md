# Example：`12_unified_collaboration.py`

> 配套 `docs/chat_layer_design.md` 的示范 example。一份文件覆盖设计文档全部关键能力——同一组 agent，五种调用形态。
>
> 文件位置：`examples/12_unified_collaboration.py`

---

## 设计意图

延续 EasyAgent 现有 examples 00–11 的层进式教学风格，第 12 层把 chat 层用一个 example 完整展示。复用同一组 Talker 跑五种形态，让读者对比"同样的对象、不同的容器/策略，行为差异在哪"。

| 形态 | 验证的设计点 |
|---|---|
| (1) sequential | Talker 协议统一 / Pipeline routing / Conducted turn-taking |
| (2) chatroom (manual) | Manual turn-taking / AgentScope MsgHub 等价 / `observe` 一等公民 |
| (3) debate (selected) | Selected/RoundRobin turn-taking / OnPredicate stop / ByJudge summarize |
| (4) nested | **Orchestrator 是 Talker** —— sequential 套 debate，关键 P4 验证 |
| (5) shared_state | 协作不通过消息流，黑板模式与对话语义并列（P6） |

---

## 完整代码

```python
"""第 12 层：统一协作模型 —— sequential / chatroom / debate / 嵌套 / 共享状态。

本例展示 chat 层的全部关键形态，使用同一组 agent：

  alice  — 创意发想
  bob    — 批判审视
  carol  — 总结归纳
  judge  — 仲裁评分

形态：
  (1) sequential           : alice -> bob -> carol（线性，谁说话由调用方决定）
  (2) chatroom (manual)    : 用户在 with 块里手动调谁，自动广播
  (3) debate (selected)    : alice/bob 轮流，judge 仲裁；judge 决定何时收尾
  (4) nested               : sequential([planner, debate_team, writer]) —— debate_team 是 (3) 整体当一棒
  (5) shared_state         : alice 写黑板、bob 读黑板（不走消息）

跑完五段，对比同一组对象在不同形态下的行为差异。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent
from easyagent.chat import (
    ChatMessage,
    Identity,
    LLMTalker,
    Orchestrator,
    SharedState,
    chatroom,
    debate,
    sequential,
)
from easyagent.chat.strategies import (
    Broadcast,
    ByJudge,
    LastMessage,
    MaxRounds,
    OnPredicate,
    Pipeline,
    Reactive,
    RoundRobin,
)
from easyagent.events import EventBus, MessageEvent


# ── 构建四个 agent，包成 Talker ────────────────────────────────────────

def make(model, name: str, role: str) -> LLMTalker:
    """把现有 ReactAgent 包成 Talker。注意：ReactAgent 不需要任何修改。"""
    return LLMTalker(
        ReactAgent(
            model=model,
            name=name,
            system_prompt=f"你是 {name}。{role}。回复保持一句话。",
            max_iterations=3,
        ),
        identity=Identity(name=name),
    )


async def main() -> None:
    model = LiteLLMModel("gemini-3-flash-preview")
    bus = EventBus()
    bus.subscribe(MessageEvent, lambda m: print(f"  [{m.sender}->{m.to}] {m.content}"))

    alice = make(model, "alice", "你擅长发散思维、提出创意")
    bob   = make(model, "bob",   "你擅长找漏洞、批判每一个想法")
    carol = make(model, "carol", "你擅长归纳总结、给出最终答案")
    judge = make(model, "judge", "你是仲裁。评分并决定争论是否结束（在 metadata 里写 finished=True 时停）")

    seed = ChatMessage(
        sender=Identity("user", role="user"),
        role="user",
        content="周末团建去哪好？",
    )

    # ── 形态 1：sequential（调用方决定顺序）─────────────────────────────
    print("\n=== (1) sequential ===")
    final = await sequential([alice, bob, carol], seed, bus=bus)
    print(f"final: {final.content}")

    # ── 形态 2：chatroom（manual，AgentScope MsgHub 等价）───────────────
    print("\n=== (2) chatroom (manual) ===")
    async with chatroom([alice, bob, carol], announcement=seed, bus=bus) as room:
        await alice()                                  # alice 自由发挥
        await bob()                                    # 收到 alice 的话再发挥
        await room.broadcast(ChatMessage(
            sender=Identity("user", role="user"),
            role="user",
            content="bob 太刻薄了换个角度",
        ))
        await carol()

    # ── 形态 3：debate（selected by judge）──────────────────────────────
    print("\n=== (3) debate ===")
    verdict = await debate(
        [alice, bob],
        judge=judge,
        max_rounds=3,
        seed=seed,
        bus=bus,
    )
    print(f"verdict: {verdict.content}")

    # ── 形态 4：nested —— sequential 套 debate ─────────────────────────
    print("\n=== (4) nested: planner -> debate_team -> writer ===")
    planner = make(model, "planner", "把用户问题拆成 2 条子问题，列出来")
    writer  = make(model, "writer",  "把仲裁结论改写成 2 句话给用户的简短回复")

    debate_team = Orchestrator(
        members={"alice": alice, "bob": bob, "judge": judge},
        routing=Broadcast(),
        turn_taking=RoundRobin(order=["alice", "bob"]),
        stop=MaxRounds(2),
        summarize=ByJudge(judge),                       # 关键：debate_team 对外只输出 judge 总结
        identity=Identity("debate_team"),
        bus=bus,
    )
    answer = await sequential([planner, debate_team, writer], seed, bus=bus)
    print(f"answer: {answer.content}")

    # ── 形态 5：共享状态（黑板模式，不走消息）─────────────────────────
    print("\n=== (5) shared state ===")
    shared = SharedState()
    shared.attach_bus(bus)

    # 给 alice 装一个写黑板工具；给 bob 装一个读黑板工具
    alice.attach_shared_state(shared, mode="write")
    bob.attach_shared_state(shared, mode="read")

    workshop = Orchestrator(
        members={"alice": alice, "bob": bob},
        routing=Broadcast(),
        turn_taking=Reactive(),
        # alice 把要点写到 "ideas" key，bob 读后给反馈，反馈写到 "critique" key
        stop=OnPredicate(lambda ctx: ctx.shared.has("critique")),
        summarize=LastMessage(),
        shared_state=shared,
        bus=bus,
    )
    await workshop(seed)
    print(f"ideas:    {shared.get('ideas')}")
    print(f"critique: {shared.get('critique')}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 该 example 验证了哪些设计点

| 验证项 | 在哪体现 |
|---|---|
| Talker 协议统一（P1） | 所有 `await xxx(seed)` 调用形态一致 |
| Orchestrator 是 Talker（P4，嵌套） | 形态 4 `debate_team` 进 sequential |
| `summarize` 决定对外消息 | 形态 4 `ByJudge`：内部 a/b 争论不外漏，只暴露 judge 结论 |
| 五种 turn_taking 同等地位（P3） | sequential→Conducted / chatroom→Manual / debate→Selected / 嵌套内→RoundRobin / workshop→Reactive |
| ChatMessage.to 路由（P2） | 形态 2 内 `bob()` 自动广播给 alice/carol |
| MultiAgentFormatter 默认装载 | 用户没写一行 prompt 拼接代码 |
| EventBus 是观测层（P5） | 同一个 bus 监听 5 种形态，UI 一套 |
| SharedState 与消息流并列（P6） | 形态 5：协作不通过消息，通过黑板 |
| 单 agent 平稳退化 | 形态 1 第一棒 alice 收到的 prompt 是普通 user/assistant，不出现 history 块 |
| `None`/silent（P7） | Reactive 模式下成员可选不发言；workshop 中 alice 写完黑板可以返回 None |
| 加法不动核（P8） | 全程使用现有 `ReactAgent`、`LiteLLMModel`、`EventBus`，不修改一行底层代码 |

---

## 验收要求（运行 example 时）

跑完输出应包含：

- **形态 1**：三条消息按 `alice → bob → carol` 顺序出现；
- **形态 2**：`announcement` 一次广播 + 三次手动调用，bob 看到 alice 的内容；
- **形态 3**：debate 在 ≤ 3 轮内由 judge 触发停止；
- **形态 4**：writer 看到的输入是 judge 的总结而不是 a/b 的原始争论（**P4 关键验证**）；
- **形态 5**：`shared.ideas` / `shared.critique` 都有值，且**没有任何 ChatMessage 携带这些内容**（说明协作走的是黑板，不是消息）。

---

## 与现有 examples 的关系

| Example | 角色 |
|---|---|
| 00–05 | 单 agent，从模型调用到记忆/工具/sandbox |
| 06 PipelineRuntime | 旧版"线性串联"实现：基于 EndTool + Runtime |
| 07–10 | 事件 / 广播 / 多 agent runtime 基础 |
| 11 group_chat | **当前最复杂的多 agent example**，~150 行，手拼 prompt，重写 `on_events` |
| **12 unified_collaboration** | **本 example。chat 层覆盖 11 全部能力，并新增嵌套与黑板协作** |

第 11 层在 chat 层落地后可显著简化（≤ 50 行），保留下来作为"runtime 层手工实现"的对照——读者看完两份，能直观理解 chat 层抽象带来的简化。

---

## 实施提示

按 `docs/chat_layer_design.md §12` 改造清单顺序实施：

1. 完成 1–3 步（`ChatMessage` / `Talker` / `MultiAgentFormatter`）即可让形态 1 跑通；
2. 完成 4–5 步（策略 + Orchestrator）解锁形态 2、3；
3. 完成 6 步（SharedState）解锁形态 5；
4. 完成 7 步（presets）让 example 代码缩到当前长度；
5. 完成 9 步（RuntimeTalker）后即可在嵌套位置直接放一个 `TickBasedRuntime`，进一步统一两条路径。

每步都能独立验收，不需要 big-bang 重构。
