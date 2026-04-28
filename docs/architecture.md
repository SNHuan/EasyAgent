# EasyAgent Architecture

EasyAgent 是一个分层 SDK。每一层只解决一个问题，可以学完一层再进入下一层。

```text
Model
  -> Memory + Context
  -> Agent  (Agent / ReactAgent / SkillAgent / SandboxAgent)
  -> Tool / Skill / Sandbox
  -> AgentSession
  -> Talker / Orchestrator / SharedState           ← chat 层（多 agent 默认入口）
  -> Event / Runtime / Policy                      ← 进阶：tick 调度 / 自主仿真
```

整个 SDK 围绕**两条主线**：

```text
单 agent 主线：  Model + Memory + Context + Tool + AgentSession  →  ReactAgent / SkillAgent / SandboxAgent
多 agent 主线：  Talker (协议)  +  Orchestrator (容器)  +  SharedState (黑板)
                ↑ 这一层就是 chat 层；它把"多 agent 协作"变成普通的 await 函数调用。

Runtime 层是**进阶逃生通道**：tick 调度、policy 体系、自主群体仿真。
                绝大多数多 agent 任务用 chat 层就够，不需要碰 Runtime。
```

> 心智模型：
> - **Agent** 是定义；**AgentSession** 是实例；
> - **Talker** 是"谁能说话"的统一抽象；**Orchestrator** 是 Talker 的容器（且自身也是 Talker，可嵌套）；
> - **Runtime** 是 tick-based 的并发世界，给需要异步独立调度的场景用。

## 1. Model

模型层是 SDK 中唯一直接和 LLM provider 通信的层。

- `BaseLLM` 定义适配契约。
- `LiteLLMModel` 通过 LiteLLM 实现该契约。
- `Message`、`ToolCall`、`LLMResponse` 定义 SDK 的消息 schema。

`Message` 带一个可选的 `name` 字段——chat 层用它在多 agent prompt 里区分自己和他人，单 agent 场景下可忽略。

## 2. Memory and Context

Memory 存对话状态。Context 决定每次发给模型的是哪一部分。

- `BaseMemory` 存消息。
- `InMemoryMemory` 是默认的进程内实现。
- `BaseContext` 把 memory 渲染成模型消息。
- `FullContext`、`SlidingWindowContext`、`SummaryContext` 是单 agent 的渲染策略。
- `MultiAgentFormatter`（chat 层）是多 agent 场景的渲染策略——把别人的发言折叠成 user 消息里的 `<history>` 块，避免 LLM 把别人的话当成自己说过的。

## 3. Agent

`Agent` 是**可复用配置**——它描述"这个 agent 是什么"，但**不直接代表某次正在运行的对话或任务**。

```text
Agent = Model + MemoryFactory + ContextStrategy + (子类引入的 tools/skills/sandbox) + Instructions
```

SDK 提供四个具体 agent 类，通过继承叠加能力：

| 类 | 行为 |
|---|---|
| `Agent` | 单轮模型调用。一次 `run()` = 一次 LLM 调用。 |
| `ReactAgent(Agent)` | ReAct 循环：模型调用 → 工具调用 → 模型调用 → ... 直到调用 `end` 工具或达到 `max_iterations`。 |
| `SkillAgent(ReactAgent)` | 在 ReactAgent 基础上，注入 `load_skill` / `list_skill_files` / `read_skill_file` / `run_skill_script` 四个工具，模型可以按需加载 SKILL.md 包并激活其工具。 |
| `SandboxAgent(ReactAgent)` | 在 ReactAgent 基础上，自动注册 `bash` / `write_file` / `read_file` 三个工具，并通过 `on_session_start` / `on_session_end` 管理沙箱生命周期。 |

**Agent 不持有运行态**：当前对话 memory、当前任务状态、当前 sandbox 实例等都不属于 Agent，而属于 AgentSession。`Agent` 只持有 `_memory_factory` 与 `_context_factory`，它们在 `create_session()` 时被克隆为该 session 独立的实例。

`BaseAgent.observe(msg)` 是新增的"只看不回"入口——把消息写进 session memory 但不触发 loop。chat 层的 Talker 协议在底层就靠这个。

## 4. Tool / Skill / Sandbox

三个相关但不同层的概念：

- **Tool**：模型可见的可调用函数。
- **Skill**：一个目录包，包含必需的 `SKILL.md` 入口文件，以及可选的 `references/`、`templates/`、`assets/`、`scripts/`。
- **Sandbox**：工具执行所在的环境（`LocalSandbox` 或 `DockerSandbox`）。

需要沙箱的工具（`bash` / `write_file` / `read_file`）从 `session.sandbox` 直接读取，不再通过字符串 key 索引。

## 5. AgentSession

`AgentSession` 是某个 Agent 在某次执行中的**运行实例**——也就是 agent 的"分身"。

```text
AgentSession = Agent 引用 + Memory + 渲染状态 + Resources + 当前任务状态
```

每个 session 都有自己的：

- `session_id`、对所属 `agent` 的引用；
- `memory`、`context`、`enabled_tools`、`loaded_skills`；
- `sandbox`、`resources`；
- `event_bus`（Runtime 注入时存在）、`metadata`、`status`、`iteration_count`、`final_output`、`loop_state`、`loop_steps`。

### 三个执行入口

```python
class AgentSession:
    async def run(self, user_input) -> str:
        """运行直到完成。Agent.run 通过它驱动单次任务。"""

    async def step(self) -> LoopStepResult:
        """跑一次 step（一次模型调用，可能加多次工具调用）。"""

    async def on_events(self, events) -> list[BaseEvent]:
        """处理一组 events 并产出新 events。Runtime 通过它驱动 session。"""
```

- `run` / `step` 是单任务入口，chat 层和单 agent 场景都用它们。
- `on_events` 是 **runtime 层** 的接入点，只有 tick-based runtime 才会走到。

## 6. Chat 层（多 agent 默认入口）

Chat 层是 `easyagent.chat` 子包提供的用户面 API。它把"多 agent 协作"抽象成同一个协议下的普通函数调用——**不用 event、不用 policy、不用 tick**。

### 6.1 Talker 协议

```python
class Talker(Protocol):
    identity: Identity

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str = "default",
    ) -> ChatMessage | None:
        """处理消息（如果有）并产生回复。返回 None 表示这一轮选择沉默。"""

    async def observe(self, msg: ChatMessage) -> None:
        """只接收消息进入记忆，不产生回复。"""
```

四种内置实现：

| 实现 | 角色 |
|---|---|
| `LLMTalker` | 包装现有的 `BaseAgent`（ReactAgent / SkillAgent / SandboxAgent 任一）。每个 channel 一个独立 session。 |
| `HumanTalker` | 通过 input/异步 queue 接 UI 或终端，让人类作为 Talker 参与。 |
| `Orchestrator` | 多 Talker 容器（见 §6.3）。**它本身也是 Talker**——这就是嵌套的关键。 |
| `RuntimeTalker` | 把整个 Runtime 包成 Talker，让 tick-based runtime 可以嵌进 chat 层。 |

### 6.2 ChatMessage：自带路由的消息单位

```python
@dataclass
class ChatMessage:
    sender: Identity                                       # 谁说的
    content: str | list[Block]
    to: Literal["*"] | frozenset[str] = "*"                # 发给谁
    channel: str = "default"                               # 哪个房间
    role: Literal["user", "assistant", "system", "tool"]
    reply_to: str | None = None                            # 回的哪条
    metadata: dict = ...
```

关键：**路由信息（`to` / `channel`）写在消息上**，不写在订阅器上。这让 `await alice(msg)` 这种直接调用就能完整表达"alice 给 bob 发了个私信"，没有外部状态。

`ChatMessage` 与 `Message` / `MessageEvent` 各司其职：
- `Message`（model 层）：LLM API 协议格式；
- `MessageEvent`（events 层）：bus 上的事件载荷；
- `ChatMessage`（chat 层）：用户和 Talker 之间收发的对话单位。

`MultiAgentFormatter` 负责 `list[ChatMessage] → list[Message]` 的转换，用户不感知。

### 6.3 Orchestrator：多 Talker 容器

`Orchestrator` 把一组成员 Talker 编排起来执行一段对话。它由四个**正交策略**驱动：

```python
@dataclass
class Orchestrator:
    members: dict[str, Talker]
    routing: Routing                # Q3: 谁能听见每条消息？
    turn_taking: TurnTaking         # Q2: 下一个谁说话？
    stop: StopCondition             # Q4: 何时结束？
    summarize: Summarize            # Q6: 容器对外说什么？
    identity: Identity
    bus: EventBus | None = None
    shared_state: SharedState | None = None
```

**Orchestrator 自己也实现 Talker 协议**——它的 `__call__(msg) → ChatMessage` 签名和单个 Talker 完全一样。这是嵌套能力的来源：把一个 Orchestrator 当成成员塞进另一个 Orchestrator，外层无需知道内层有多复杂。

`summarize` 决定容器对外说什么——比如 `ByJudge(judge)` 让一个 debate 容器只对外暴露 judge 的一句结论，alice/bob 的内部争论不外漏。这就是嵌套场景下"封装边界"的实现。

### 6.4 五个 Preset

```python
sequential([t1, t2, t3], "go")          # 流水线，调用方写死顺序
chatroom([t1, t2], announcement="...")  # 用户在 with 块里写 if/else 决定下一棒
groupchat([t1, t2, t3])                 # LLM 在 msg.to 里 @ 下一棒
debate([t1, t2], judge=t3)              # 第三方仲裁产出结论
fanout([t1, t2, t3], "...")             # 同一 seed 同时丢给所有人
```

每个 preset 都只是 `Orchestrator(...)` 的薄工厂，没有特殊代码路径。

### 6.5 SharedState：黑板协作

不是所有协作都该走对话。共编一份文档、投票、累积评分、等待外部信号——这些场景把状态硬塞进消息里很别扭。

`SharedState` 提供版本化的并发安全 KV，配合 `OnSharedKey` 停止条件、`FromSharedState` summarize 策略，可以让一个 Orchestrator **完全不发消息**也能协作并停止。

```python
shared = SharedState()
shared.subscribe("score", lambda v: print(f"score updated to {v}"))
await shared.wait_for("final_report")        # 异步等待
shared.attach_bus(bus)                        # 写入时发 StateChangedEvent
```

## 7. Runtime 层（进阶）

Runtime 层是 chat 层下面的另一种执行模型。它不是 chat 层的实现细节，而是**一种平行的、面向异步并发的多 agent 执行环境**。

```text
Runtime = AgentSession 集合 + EventBus + 调度器（policy 三件套） + 停止控制
```

### 7.1 关键 API

```python
runtime = ShuffledRuntime(
    agents={"alice": AliceAgent(...), "bob": BobAgent(...)},
    step_policy=DeliverToRecipients(),
    stop_policy=AnyOf([StopWhenIdle(grace_steps=1), StopAfterTicks(max_ticks=5)]),
)
result = await runtime.run([MessageEvent(sender="user", to="*", content="...")])
```

### 7.2 三种调度策略

`SchedulePolicy.order(session_ids, state)` 返回**批列表**：每批内并发，批与批顺序执行。

- `Parallel`：`[[a, b, c]]` — 一批全并发，同 tick 内互不见。
- `Sequential`：`[[a], [b], [c]]` — 每个 session 一批，固定顺序，前一个的输出对后一个可见。
- `Shuffled`：每个 session 一批，顺序随机——最贴近"谁先看到群消息"的社会模拟。

`ParallelRuntime` / `SequentialRuntime` / `ShuffledRuntime` 是 schedule_policy 的薄预设。

### 7.3 Step / Stop policy

- **`StepPolicy`** 决定一个事件要投递给哪些 session：
  - `DeliverToRecipients` 按 `MessageEvent.to` 投递；
  - `TickDriven` 忽略事件流，每 tick 给所有 session 一个 tick 信号让它们自行决定是否说话。
- **`StopPolicy`** 决定何时终止：
  - `StopWhenIdle` / `StopAfterTicks` / `StopAfterEvents` / `StopWhenMessageMatches` / `AnyOf`。

### 7.4 Event 与 EventBus

- **MessageEvent**（agent-to-agent 消息）通过 EventBus 广播 + StepPolicy 投递。
- **WaitEvent**（Runtime 控制事件）当一个 session 的 `on_events` 返回 `WaitEvent` 时，Runtime 把该 session 标记为"下一 tick 重新唤醒"，**不进入 bus 历史**。
- **遥测事件**（`LLMCalledEvent` / `LLMRespondedEvent` / `ToolCalledEvent` / `ToolResultEvent`）支持离线分析。

EventBus 在 chat 层和 runtime 层是同一个东西，但承担的角色不同——chat 层把它当观测旁路（消息直送，bus 只复制一份做日志）；runtime 层把它当传输总线（事件就是消息）。

## 8. Talker 机制 vs Runtime 机制

这两套机制都解决"多 agent 协作"，但**模型完全不同**——选错了会很别扭。下面是对照表：

| 维度 | Talker（chat 层） | Runtime（runtime 层） |
|---|---|---|
| **核心抽象** | `Talker.__call__(msg) → msg` —— 像普通函数 | `session.on_events(events) → events` —— 事件管道 |
| **谁驱动循环** | **调用方**（`await orch(msg)` 拿结果就走） | **Runtime 自己**的 tick loop |
| **执行模型** | 同步：一次发一个，等到回复 | 异步：每 tick 给所有 session 一次"事件批"，结果汇总成下批输入 |
| **下一棒谁说话** | `TurnTaking` 策略**在容器内**决定，每轮一次 | `SchedulePolicy` 决定本 tick 跑哪些 session、是否并发 |
| **何时停** | `StopCondition` 看历史决定，每轮检查 | `StopPolicy` 看 tick 状态决定，整轮检查 |
| **组合性** | Orchestrator 自身是 Talker，**天然嵌套** | Runtime 不是 agent，要嵌套必须用 `RuntimeTalker` 包一层 |
| **路由表达** | 写在 `ChatMessage.to` 上，是数据 | 由 `StepPolicy` 决定，是策略 |
| **观测** | `bus` 是旁路，**不参与传输** | `bus` 既是观测又是事实上的总线 |
| **典型用例** | pipeline / 群聊 / 嵌套子系统 / 黑板协作 | 社会仿真 / 自主群体 / 强并发批处理 / tick-based 调度 |
| **代价** | 同步语义，单线流；做并发要靠 `fanout` | 概念多（事件 / policy 三件套 / tick），心智成本高 |

### 什么时候用 Talker？

绝大多数场景。包括：

- 「先 A 再 B 再 C」（`sequential`）；
- 「我在循环里决定下一棒谁说」（`chatroom` + if/else）；
- 「让 LLM 自己决定下一棒」（`groupchat`）；
- 「多人辩论 + 第三方仲裁」（`debate`）；
- 「一个子系统作为更大 pipeline 里的一棒」（任意 Orchestrator 嵌套）；
- 「成员之间通过黑板协作」（`SharedState` + `OnSharedKey`）。

写法：`await sequential([...], "...")` / `async with chatroom(...)` / `await orch(msg)`。

### 什么时候用 Runtime？

只有真正需要 **tick-based 并发调度** 的场景：

- 每个 agent 都有"自己的"循环节奏，不是被外层调用方推动的；
- 需要 `Shuffled` / `Parallel` 这种"同 tick 内多人发言"的语义；
- 需要 `WaitEvent` 让一个 agent "跳过这轮等下轮"；
- 需要订阅 bus 上的 `MessageEvent` 历史做仿真分析；
- 自主群体仿真——「谁先看到群消息谁先回复」这种社会模拟。

写法：手写 `AgentSession.on_events`、配 `StepPolicy` / `SchedulePolicy` / `StopPolicy`、`runtime.run([MessageEvent(...)])`。`examples/14_advanced_runtime.py` 就是一个完整例子。

### 两层互通

它们不是非此即彼，可以**双向互嵌**：

```python
# 把 runtime 当 Talker 嵌进 chat 层
sim = ShuffledRuntime(agents={...}, ...)
final = await sequential([planner, RuntimeTalker(sim), writer], "...")

# 也可以反过来——一个 chat-layer Orchestrator 实现了 Talker 协议，
# 包一层适配后也可以作为 runtime 的 agent。
```

EventBus 在两层之间充当公共观测层——给 chat 层的 Orchestrator 传一个 bus，给 runtime 也用同一个 bus，UI 一套订阅代码就能监听两边。

## 9. 数据流

### 单 Agent 执行（不变）

```text
Agent.run(user_input)
  └─ Agent.create_session()
  └─ Agent.on_session_start(session)
  └─ Agent.run_session(session, user_input)
       └─ loop: Agent.step(session)         # 直到 done
  └─ Agent.on_session_end(session)
  └─ return AgentRunResult.from_session(session)
```

### Chat 层多 Talker 协作

```text
Orchestrator.__call__(msg)
  └─ ctx = TurnContext(members, channel, history=[], ...)
  └─ if msg: routing.targets(msg, ctx) → 各 member.observe(msg)
  └─ turn loop:
       │ stop.check(ctx) → 决定是否退出
       │ turn_taking.next(ctx) → 选下一发言者
       │ reply = await member()             # Talker 协议调用
       │ routing.targets(reply, ctx) → 路由给其他成员 observe
       │ ctx.history.append(reply)
  └─ summarize.produce(ctx, identity) → 容器对外的 ChatMessage
```

### Runtime 层多 AgentSession 协作

```text
Runtime.run(seed_events)
  └─ enter all sessions (on_session_start)
  └─ tick loop:
       │ StepPolicy.deliveries(event, sessions, state) → Deliveries
       │ SchedulePolicy.order(session_ids, state) → [[batch1], [batch2], ...]
       │ for batch:
       │     gather(session.on_events(events) for each session in batch)
       │     produced events:
       │       • WaitEvent  → 调度该 session 下 tick 重跑（不上 bus）
       │       • 其他事件   → _state.events + bus.publish + 后续 batch 可见
       │ StopPolicy.should_stop(state)
  └─ exit all sessions (on_session_end)
  └─ RuntimeResult(state, messages)
```

## 10. Public API

```python
# 单 agent + 工具
from easyagent import (
    Agent, ReactAgent, SkillAgent, SandboxAgent,
    AgentSession, AgentRunResult,
    LiteLLMModel, Message,
    ToolManager, SkillManager, register_tool,
    EventBus, MessageEvent,
)

# 多 agent：chat 层（默认入口）
from easyagent.chat import (
    ChatMessage, Identity, Talker,
    LLMTalker, HumanTalker, RuntimeTalker,
    Orchestrator, ManualSession,
    SharedState, StateChangedEvent,
    MultiAgentFormatter,
    sequential, fanout, chatroom, groupchat, debate,
)
from easyagent.chat.strategies import (
    Routing, Broadcast, Direct, Pipeline,
    TurnTaking, Conducted, Reactive, RoundRobin, Random, Weighted, Selected, Manual,
    StopCondition, MaxRounds, Idle, AfterAllSpoken, OnPredicate, OnSharedKey, AnyOf, AllOf,
    Summarize, LastMessage, Aggregate, ByJudge, FromSharedState, Custom,
)

# 进阶：runtime 层
from easyagent.runtime import (
    BaseRuntime, TickBasedRuntime,
    ParallelRuntime, SequentialRuntime, ShuffledRuntime,
    Parallel, Sequential, Shuffled,                  # SchedulePolicy
    DeliverToRecipients, TickDriven,                 # StepPolicy
    StopWhenIdle, StopAfterTicks, StopAfterEvents,   # StopPolicy
    StopWhenMessageMatches, AnyOf,
)
from easyagent.events import (
    BaseEvent, WaitEvent,
    LLMCalledEvent, LLMRespondedEvent,
    ToolCalledEvent, ToolResultEvent,
)
```

## 11. 命名速查

| 概念 | 类型 | 层 | 说明 |
|---|---|---|---|
| `Agent` / `BaseAgent` | 类 | agent | 单 agent 定义 + 最小契约 |
| `ReactAgent` / `SkillAgent` / `SandboxAgent` | 类 | agent | 加上工具 / 技能 / 沙箱的 ReAct agent |
| `AgentSession` | 类 | agent | agent 的运行实例（分身） |
| **`Talker`** | Protocol | **chat** | 「能说话」的统一抽象 |
| `LLMTalker` / `HumanTalker` / `RuntimeTalker` | 类 | chat | Talker 的具体实现 |
| `ChatMessage` / `Identity` | 类 | chat | 用户层对话原语 |
| **`Orchestrator`** | 类 | **chat** | 多 Talker 容器，自身也是 Talker |
| `Routing` / `TurnTaking` / `StopCondition` / `Summarize` | Protocol | chat | Orchestrator 的四种策略 |
| `sequential` / `fanout` / `chatroom` / `groupchat` / `debate` | 函数 | chat | preset 工厂 |
| `SharedState` | 类 | chat | 黑板协作原语 |
| `MultiAgentFormatter` | 类 | chat | 多 agent prompt 渲染（替代 SlidingWindowContext） |
| **`Runtime`** / `TickBasedRuntime` | 类 | **runtime** | tick-based 多 session 执行环境 |
| `EventBus` | 类 | events | 事件记录与分发（chat / runtime 共用） |
| `MessageEvent` / `WaitEvent` | 类 | events | 通信原语 / Runtime 控制事件 |
| `StepPolicy` / `SchedulePolicy` / `StopPolicy` | Protocol | runtime | 事件投递 / 单 tick 顺序 / 终止条件 |
| `session.run` / `step` / `on_events` | 方法 | agent | 单任务 / 单步 / runtime 入口 |
| `BaseAgent.observe(msg)` | 方法 | agent | 只看不回 |
