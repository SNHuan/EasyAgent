# EasyAgent Architecture

EasyAgent 是一个分层 SDK。每一层只解决一个问题，可以学完一层再进入下一层。

```text
Model
  -> Memory + Context
  -> Agent  (Agent / ReactAgent / SkillAgent / SandboxAgent)
  -> Tool / Skill / Sandbox
  -> AgentSession
  -> Event
  -> Runtime
```

整个 SDK 围绕**三个核心概念**展开：

```text
Agent        = 可复用配置与行为定义（"角色设定"）
AgentSession = Agent 在某次执行中的运行实例（"分身"）
Runtime      = 多个 AgentSession 共享的执行环境（"世界"）
```

> 心智模型：Agent 是定义；AgentSession 是实例；Runtime 是世界；Event 是通信；
> 循环逻辑直接写在 agent 自己的 `step()` 方法里。

## 1. Model

模型层是 SDK 中唯一直接和 LLM provider 通信的层。

- `BaseLLM` 定义适配契约。
- `LiteLLMModel` 通过 LiteLLM 实现该契约。
- `Message`、`ToolCall`、`LLMResponse` 定义 SDK 的消息 schema。

这层让上层与具体 provider 解耦。

## 2. Memory and Context

Memory 存对话状态。Context 决定每次发给模型的是哪一部分。

- `BaseMemory` 存消息。
- `InMemoryMemory` 是默认的进程内实现。
- `BaseContext` 把 memory 渲染成模型消息。
- `FullContext`、`SlidingWindowContext`、`SummaryContext` 是不同的渲染策略。

当一个 agent 的历史超出每轮可发送量时，这一拆分是必要的。

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

**循环逻辑直接写在 `Agent.step()` 里**，不再有单独的 `Loop` 层。`Agent.step()`
做单次模型调用并立即结束；`ReactAgent.step()` 做一轮模型调用 + 工具执行；
`run_session()` 反复调 `step()` 直到任务完成。

**Agent 不持有运行态**：当前对话 memory、当前任务状态、当前 sandbox 实例、
当前 inbox / outbox 等都不属于 Agent，而属于 AgentSession。`Agent` 只持有
`_memory_factory` 与 `_context_factory`，它们在 `create_session()` 时被克隆
为该 session 独立的 `memory` / `context` 实例。Runtime 会为每个传入的 agent
创建一个独立 session。

> **关于 ContextStrategy**：`SlidingWindowContext` / `FullContext` 这类策略
> 本身可能是无状态的，但 `SummaryContext` 等带摘要缓存 / 压缩游标的策略会在
> session 内累积状态。规则是：**Agent 持 ContextStrategy 配置；AgentSession
> 持该策略的 per-instance 实例**——通过 `session.context = strategy.clone()`
> 保证每个分身有独立状态。

### 生命周期钩子

子类通过覆盖以下钩子接管资源管理：

```python
class SandboxAgent(ReactAgent):
    async def on_session_start(self, session):
        await self._sandbox.start()
        session.sandbox = self._sandbox

    async def on_session_end(self, session):
        try:
            await self._sandbox.stop()
        finally:
            session.sandbox = None
```

`Agent.run()` 与 Runtime 都保证：每个 session 进出一次的成对调用。

### session_class

通过给 Agent 子类设置 `session_class`，可以让 `create_session()` 返回自定义
的 AgentSession 子类：

```python
class GroupChatSession(AgentSession):
    async def on_events(self, events):
        ...

class GroupChatAgent(ReactAgent):
    session_class = GroupChatSession
```

这是把"agent 收到 events 后怎么处理"这种行为定制下放到 session 层的标准方式。

## 4. Tool / Skill / Sandbox

三个相关但不同层的概念：

- **Tool**：模型可见的可调用函数。
- **Skill**：一个目录包，包含必需的 `SKILL.md` 入口文件，以及可选的
  `references/`、`templates/`、`assets/`、`scripts/`。
- **Sandbox**：工具执行所在的环境（`LocalSandbox` 或 `DockerSandbox`）。

`SkillAgent` 加载一个 skill 时返回 `SKILL.md` 正文 + 文件清单。已加载的 skill
可以通过 `list_skill_files` / `read_skill_file` / `run_skill_script` 渐进披露
内部资源。

需要沙箱的工具（`bash` / `write_file` / `read_file`）从 `session.sandbox` 直接
读取，不再通过字符串 key 索引。

## 5. AgentSession

`AgentSession` 是某个 Agent 在 Runtime 中的**运行实例**——也就是 agent 的"分身"。

```text
AgentSession = Agent 引用 + Memory + 渲染状态 + Resources + 当前任务状态
```

每个 session 都有自己的：

- `session_id`、对所属 `agent` 的引用；
- `memory`、`context`、`enabled_tools`、`loaded_skills`；
- `sandbox`（typed slot）、`resources`（其他 session 状态）；
- `event_bus`（Runtime 注入）、`metadata`、`status`、`iteration_count`、
  `final_output`、`loop_state`、`loop_steps`。

Runtime 中每个 agent 名对应一个独立的 AgentSession，每个 session 拥有完全独立
的 memory 与状态。需要多个 worker 时，给它们不同名字即可。

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

- `run` / `step` 是单任务入口。
- `on_events` 是 multi-agent 接入点：默认实现把 MessageEvent 注入 memory、
  调 `run`、把结果包成 MessageEvent 回复。子类重写 `on_events` 来定制路由、
  格式化、`@xxx` 解析等。

子类的 `on_events` 调用 `self.run(...)` 而不是 `self.agent.run(...)`，避免
重复启停生命周期钩子。

### 默认 on_events 的回复路由（保守默认）

默认 `on_events` 的回复策略**保留输入消息的可见性**，避免在多 agent 场景下
意外形成群聊自激活循环：

- 输入是 broadcast (`to == "*"`)：回复也是 broadcast——保留"这是公开对话"的语义。
- 输入是 DM (`to == frozenset({...})`)：回复**只发回给原始 sender**，其他
  session 不会看到。

如果你的场景需要让所有 session 看到每条回复（典型的"全员群聊涌现"），重写
`on_events` 显式 broadcast，参考 `examples/11_group_chat.py` 的
`GroupChatSession`。这种场景下 SDK 让你**显式选择**而不是默认承担风险。

## 6. Event

事件是 AgentSession 之间的通信介质。

事件分两类：

- **MessageEvent**（agent-to-agent 消息）：通过 `EventBus` 广播 + `StepPolicy`
  投递给目标 session 的 `on_events`。`to` 字段决定可见性
  （`"*"` 广播 / `frozenset(...)` DM 或子组）。
- **WaitEvent**（Runtime 控制事件）：当一个 session 的 `on_events` 返回
  `WaitEvent` 时，**Runtime 直接消费它**——把该 session 标记为"下一 tick
  重新唤醒"，**不进入 `_state.events`、不发布到 bus、不通过 StepPolicy
  投递给其他 session**。这避免了"某某等待了"这种系统信号污染其他 agent 的
  上下文。

`EventBus` 还会发布 `LLMCalledEvent` / `LLMRespondedEvent` /
`ToolCalledEvent` / `ToolResultEvent` 等遥测事件，便于离线分析与监控。

`EventBus` 记录 MessageEvent 历史、分发订阅者、支持 streaming，但不参与控制
流——控制流（停止、跳过、唤醒）由 Runtime + 各 Policy 决定。

Agent / AgentSession 不互相直接调用方法，所有用户级通信都通过 MessageEvent
完成。这层让多 agent 调度可以独立演进。

## 7. Runtime

Runtime 是**多 AgentSession 共存的执行环境与调度器**。

```text
Runtime = AgentSession 集合 + EventBus + 调度器 + 共享状态 + 停止控制
```

### 关键 API

```python
runtime = SequentialRuntime(
    agents={"worker": WorkerAgent(...)},
    step_policy=DeliverToRecipients(),
    stop_policy=StopWhenIdle(),
)

# 运行前也可以继续添加 agent
runtime.add_agent("reviewer", ReviewerAgent(...))

# 注入 seed 事件
runtime.send(MessageEvent(sender="user", to="*", content="..."))

# 跑调度循环
result = await runtime.run()
```

多个 worker 直接使用多个名字：

```python
runtime = SequentialRuntime(
    agents={
        "worker-1": WorkerAgent(...),
        "worker-2": WorkerAgent(...),
        "worker-3": WorkerAgent(...),
    },
    step_policy=DeliverToRecipients(),
    stop_policy=StopWhenIdle(),
)
```

### 三种调度策略

`SchedulePolicy.order(session_ids, state)` 返回**批列表**：每批内并发，批与
批顺序执行；前一批的可见输出作为下一批的输入上下文。

- `Parallel`：`[[a, b, c]]` —— 一批全并发，同 tick 内互不见。
- `Sequential`：`[[a], [b], [c]]` —— 每个 session 一批，固定顺序，前一个的
  输出对后一个可见。
- `Shuffled`：每个 session 一批，顺序随机——最贴近"谁先看到群消息"的社会模拟。

```python
# 直接用 TickBasedRuntime + 显式策略
runtime = TickBasedRuntime(
    agents={...},
    step_policy=DeliverToRecipients(),
    stop_policy=StopWhenIdle(),
    schedule_policy=Shuffled(),
)

# 或用预设
runtime = ShuffledRuntime(agents={...}, ...)  # 等价
```

`ParallelRuntime` / `SequentialRuntime` / `ShuffledRuntime` 是 schedule_policy
的薄预设。

### Step / Stop policy

- `StepPolicy.deliveries(event, sessions, state) -> list[Delivery]` 决定一个
  事件要投递给哪些 session。`sessions` 参数是
  `Mapping[SessionId, AgentSession]`，policy 可以读取 session 状态做更精细
  的路由决策。
  - `DeliverToRecipients`：MessageEvent 按 `to` 投递（broadcast 时给除发送
    者外的所有 session）；其他事件全员可见。
  - `TickDriven`：忽略事件流，每 tick 给所有 session 同一个 _TickEvent，让
    它们自行决定是否说话。
- `StopPolicy.should_stop(state) -> (bool, reason)` 决定何时终止。
  - `StopWhenIdle` / `StopAfterTicks` / `StopAfterEvents` /
    `StopWhenMessageMatches` / `AnyOf`。

> **命名约定**：在 Policy 接口和 `Delivery` 类型中，`SessionId` /
> `session_ids` / `sessions` 指代的都是 Runtime 中的 session 实例。Runtime
> 调度的对象是 session。`SessionId` 当前是 `AgentId` (`str`) 的别名，留作
> 未来类型分化的扩展点。

### PipelineRuntime

如果场景就是固定串行交接链：

```python
pipeline = PipelineRuntime([researcher, writer, reviewer])
result = await pipeline.run("写一段产品说明。")
```

它不走 tick loop，也不使用 `StepPolicy` / `SchedulePolicy` / `StopPolicy`。
执行时按顺序调用每个 session 的 `invoke(current_input)`，并把上一棒的输出作
为下一棒的输入。非末位 agent 自动获得一个 `end(data=...)` 工具用于交接。

详细介绍见 [docs/runtime_walkthrough.md](runtime_walkthrough.md)。

## 8. 数据流

### 单 AgentSession 执行

```text
Agent.run(user_input)
  └─ Agent.create_session()
  └─ Agent.on_session_start(session)        # 子类可覆盖（SandboxAgent 启动沙箱）
  └─ Agent.run_session(session, user_input)
       └─ loop: Agent.step(session)         # 直到 done
  └─ Agent.on_session_end(session)          # 子类可覆盖（SandboxAgent 关闭沙箱）
  └─ return AgentRunResult.from_session(session)
```

### 多 AgentSession 协作

```text
Runtime.run(seed_events)
  └─ enter all sessions (on_session_start)
  └─ tick loop:
       │ StepPolicy.deliveries(event, sessions, state) -> Deliveries
       │ SchedulePolicy.order(session_ids, state) -> [[batch1], [batch2], ...]
       │ for batch:
       │     gather(session.on_events(events) for each session in batch)
       │     produced events:
       │       • WaitEvent -> Runtime control: schedule that session for next tick (not published)
       │       • other events -> _state.events + bus.publish + visible to later batches
       │ StopPolicy.should_stop(state)
  └─ exit all sessions (on_session_end)
  └─ RuntimeResult(state, messages)
```

## 9. Public API

根包暴露常用 SDK 表面：

```python
from easyagent import (
    Agent, ReactAgent, SkillAgent, SandboxAgent,
    AgentSession, AgentRunResult,
    LiteLLMModel, Message,
    EventBus, MessageEvent,
    ToolManager, SkillManager, register_tool,
)
```

进阶扩展点放在子包里：

```python
from easyagent.context import FullContext, SlidingWindowContext, SummaryContext
from easyagent.memory import InMemoryMemory
from easyagent.runtime import (
    BaseRuntime, TickBasedRuntime, PipelineRuntime,
    ParallelRuntime, SequentialRuntime, ShuffledRuntime,
    Parallel, Sequential, Shuffled,                 # SchedulePolicy
    DeliverToRecipients, TickDriven,                # StepPolicy
    StopWhenIdle, StopAfterTicks, StopAfterEvents,  # StopPolicy
    StopWhenMessageMatches, AnyOf,
    SharedStore,
)
from easyagent.events import (
    BaseEvent, WaitEvent,
    LLMCalledEvent, LLMRespondedEvent,
    ToolCalledEvent, ToolResultEvent,
)
```

## 10. 命名速查

| 概念 | 类型 | 说明 |
|---|---|---|
| `Agent` / `BaseAgent` | 类 | 单轮 agent 定义 + Runtime 看到的最小契约 |
| `ReactAgent` | 类 | ReAct 循环 + 工具调用 |
| `SkillAgent` | 类 | ReactAgent + SKILL.md 按需加载 |
| `SandboxAgent` | 类 | ReactAgent + 沙箱生命周期管理 |
| `AgentSession` | 类 | agent 的运行实例（分身） |
| `Runtime` / `TickBasedRuntime` | 类 | 多 session 执行环境 |
| `PipelineRuntime` | 类 | 固定串行交接链 |
| `EventBus` | 类 | 事件记录与分发 |
| `MessageEvent` / `WaitEvent` | 类 | 通信原语 / Runtime 控制事件 |
| `StepPolicy` | Protocol | 事件投递策略 |
| `SchedulePolicy` | Protocol | 单 tick 内执行顺序 |
| `StopPolicy` | Protocol | 终止条件 |
| `session_class` | 类属性 | Agent 挂自定义 AgentSession 子类 |
| `session.run` | 方法 | 跑到完成（单任务入口） |
| `session.step` | 方法 | 跑一次 step |
| `session.on_events` | 方法 | 处理 events，Runtime 入口 |
| `runtime.add_agent` | 方法 | 添加一个 agent 并创建对应 session |
| `runtime.send` | 方法 | 注入 seed 事件 |
