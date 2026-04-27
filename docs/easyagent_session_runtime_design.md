# EasyAgent Session 与 Runtime 设计

> 本文档描述 EasyAgent 0.3.x 中 `Agent` / `AgentSession` / `Runtime` 三者的
> 职责划分、组合方式与设计取舍。它不是教程，而是写给"想理解 SDK 内部为什么
> 这么分层"的读者的设计参考。
>
> 教程性文档参见 [docs/architecture.md](docs/architecture.md) 与
> [docs/runtime_walkthrough.md](docs/runtime_walkthrough.md)。

## 1. 背景

EasyAgent 在 0.2.x 之前，`Agent` 同时承担了两件事：

1. **可复用配置**：定义"这个 agent 是什么"——哪个模型、什么工具、什么 prompt。
2. **运行中实体**：持有 conversation memory、当前任务状态、当前 sandbox 实例。

当系统从单 agent 扩展到多 agent 协作时，这种合并立刻产生问题：

- 同一个 agent 配置能不能被多次复用？
- 一个 agent 的"多个分身"各自的 memory / sandbox 在哪？
- 多 agent 调度逻辑由谁负责？
- 谁是 runtime 的最小调度单位？

0.3.0 给出的答案是把 Agent 拆成三层：

```text
Agent        = 可复用的配置与行为定义
AgentSession = Agent 在某次执行中的运行实例
Runtime      = 多个 AgentSession 共享的执行环境与调度器
```

后续章节展开每一层的具体职责、API 与边界。

---

## 2. Agent

### 2.1 定位：可复用配置

`Agent` 描述"这个 agent 是什么"，但**不直接代表某次正在运行的对话或任务**。

```text
Agent = Model + MemoryFactory + ContextStrategy + Instructions
        + (子类引入的) tools / skills / sandbox
```

`Agent` 持有的字段都是配置或工厂：

- `_default_model`：底层 LLM 适配器；
- `_memory_factory` / `_context_factory`：在 `create_session()` 时被克隆；
- `_system_prompt` / `name` / `description`：标识与默认 prompt；
- `_max_steps`：循环步数上限；
- `session_class`：决定 `create_session()` 返回哪种 `AgentSession` 子类。

**不在 Agent 上**的状态：当前 conversation memory、当前 sandbox 实例、当前
任务进度、当前 inbox / outbox、event_bus 引用。这些都属于 `AgentSession`。

### 2.2 四个具体 agent 类（继承链）

| 类 | 行为 |
|---|---|
| `Agent` | 单轮 LLM 调用。`run()` = 一次模型调用即结束。 |
| `ReactAgent(Agent)` | ReAct 循环：模型 → 工具调用 → 模型 → ... 直到调用 `end` 工具或达到 `max_iterations`。 |
| `SkillAgent(ReactAgent)` | 在 ReactAgent 基础上注入 `load_skill` / `list_skill_files` / `read_skill_file` / `run_skill_script`，模型可按需加载 SKILL.md 并激活其工具。 |
| `SandboxAgent(ReactAgent)` | 在 ReactAgent 基础上自动注册 `bash` / `write_file` / `read_file`，并通过生命周期钩子管理沙箱。 |

> **为什么循环不是单独的 Layer？** 0.2.x 曾把 `Loop` 抽出为独立模块
> （`SingleTurnLoop` / `ReActLoop`）。实践发现循环逻辑和"这个 agent 用什么
> 工具" 紧耦合——分离后总是要把 prompt、tool schema、telemetry 来回传。
> 0.3.x 把循环逻辑下沉到 agent 自己的 `step()` 方法里：`Agent.step()` 是单
> 轮调用，`ReactAgent.step()` 是一轮"模型 + 工具"。`run_session()` 反复调
> `step()` 直到任务完成。这是一处刻意去掉的抽象。

### 2.3 生命周期钩子

子类通过覆盖以下钩子接管资源：

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

`Agent.run()`（单任务）与 Runtime（多 agent）都保证：每个 session 进出一次
的成对调用。

### 2.4 session_class

通过给 Agent 子类设置 `session_class`，可以让 `create_session()` 返回自定义
的 AgentSession 子类。这是把"agent 收到 events 后怎么处理"这种行为定制下放
到 session 层的标准方式：

```python
class GroupChatSession(AgentSession):
    async def on_events(self, events):
        ...

class GroupChatAgent(ReactAgent):
    session_class = GroupChatSession
```

---

## 3. AgentSession

### 3.1 定位：Agent 的运行实例（"分身"）

`AgentSession` 表示某个 `Agent` 在某次执行中的**具体实例**。Runtime 调度的
最小单位是 session，不是 agent。

```text
AgentSession = Agent 引用 + Memory + 渲染状态 + Resources + 当前任务状态
```

### 3.2 字段（实际定义见 `easyagent/agent/session.py`）

```python
@dataclass
class AgentSession:
    session_id: str
    agent: BaseAgent
    memory: BaseMemory
    context: BaseContext
    enabled_tools: list[str]
    loaded_skills: list[str]
    sandbox: BaseSandbox | None
    resources: dict[str, Any]
    metadata: dict[str, Any]
    event_bus: EventBus | None
    status: AgentStatus
    iteration_count: int
    final_output: str | None
    loop_steps: list[LoopStepResult]
    loop_state: dict[str, Any]
```

设计取舍：

- `sandbox` 是**显式的 typed slot**，不是 `resources` 字典里的一个 key。
  原因：需要 sandbox 的工具（`bash` / `write_file`）频繁访问它，typed slot
  让 IDE 与 mypy 都能理解；用 `resources["sandbox"]` 就丢失了类型。
- `loop_state` 是开放 dict，给 ReAct 循环存"是否被外部 StopEvent 提前终止"
  这类瞬态信号。Runtime 通过写入 `loop_state["__early_exit__"]` 让正在循环的
  agent 在下一个工具调用边界主动退出。
- `event_bus` 是**Runtime 注入**的，单 agent 模式下为 `None`。telemetry
  事件（`LLMCalledEvent` / `ToolCalledEvent` 等）只在 `event_bus` 存在时发
  出——这避免了"用 SDK 跑单元测试时也会订阅一堆事件"的开销。

### 3.3 三个执行入口

```python
class AgentSession:
    async def run(self, user_input) -> str: ...
    async def step(self) -> LoopStepResult: ...
    async def on_events(self, events) -> list[BaseEvent]: ...
```

| 入口 | 调用方 | 语义 |
|---|---|---|
| `run` | `Agent.run` 单任务 | 把 user_input 加进 memory，反复 `step` 直到完成。 |
| `step` | 内部 / 高级用户 | 跑一次循环步（一次模型调用，可能含多次工具调用）。 |
| `on_events` | Runtime | 处理一组事件，产出新事件。 |

> **为什么 `on_events` 而不是 `step(events)`？** 早期版本 `step` 同时承担
> "单步循环" 和 "多 agent 接入点" 两个语义，签名互相冲突。0.3.x 拆成两个
> 方法：`step` 是单 session 的循环原语，`on_events` 是多 agent 的事件入口。
> 子类重写 `on_events` 不会污染 `step`。

### 3.4 默认 on_events 的回复路由

默认 `on_events` 实现保持**保守**：

- 输入是 broadcast (`to == "*"`)：回复也是 broadcast——保留"这是公开对话"
  的语义。
- 输入是 DM：回复**只发回原始 sender**，避免群聊自激活循环。

群聊涌现场景需要**显式**重写 `on_events` 选择 broadcast，参见
`examples/11_group_chat.py`。这是有意的——SDK 不替你承担"无意中让所有人不
停回复" 的运行时风险。

---

## 4. Runtime

### 4.1 定位：多 session 共存的世界

```text
Runtime = AgentSession 集合 + EventBus + 调度器 + 共享状态 + 停止控制
```

### 4.2 类层次

```text
BaseRuntime                   # 抽象：sessions + bus + state + run() abstract
  └─ TickBasedRuntime         # tick 主循环 + StepPolicy / SchedulePolicy / StopPolicy
        ├─ ParallelRuntime    # 预设 Parallel
        ├─ SequentialRuntime  # 预设 Sequential
        └─ ShuffledRuntime    # 预设 Shuffled
  └─ PipelineRuntime          # 不走 tick loop，固定串行交接链
```

### 4.3 关键 API（实际签名）

```python
runtime = SequentialRuntime(
    agents={"alice": alice_agent, "bob": bob_agent},
    step_policy=DeliverToRecipients(),
    stop_policy=StopAfterTicks(4),
)

# 添加 agent（等价于在 agents= 里直接放进去）
runtime.add_agent("reviewer", ReviewerAgent(...))

# 注入 seed event（下次 run() 消费）
runtime.send(MessageEvent(sender="user", to="*", content="..."))

# 启动调度循环
result = await runtime.run([
    MessageEvent(sender="user", to="alice", content="hello")
])
```

`add_agent(name, agent)` 内部完成：

```python
session = agent.create_session()
session.session_id = name
session.agent = agent
session.event_bus = self._bus
self.sessions[name] = session
```

> **为什么不是 `register_agent` + `spawn`？** 早期 RFC 提议过模板注册 +
> 显式 spawn 的 API。落地实践中发现：用户绝大多数场景就是"给我一个名字一个
> agent"。模板注册带来一个不必要的间接层。多个 worker 直接在 `agents=` 里
> 放不同名字就行：
>
> ```python
> agents={"worker-1": WorkerAgent(...), "worker-2": WorkerAgent(...)}
> ```

### 4.4 Tick loop 与三种调度策略

`TickBasedRuntime._run_tick_loop` 的简化形态：

```text
pending = seed events 经 StepPolicy 路由后的 deliveries

while True:
    state.tick += 1
    if stop_policy.should_stop(state):
        break

    next_pending = []
    if pending:
        produced = _run_batch(pending)         # 按 schedule_policy 分批执行
        next_pending += _handle_produced_events(produced)

    tick_deliveries = step_policy.deliveries_on_tick(...)
    if tick_deliveries:
        produced = _run_batch(tick_deliveries)
        next_pending += _handle_produced_events(produced)

    pending = next_pending
```

`SchedulePolicy.order(session_ids, state)` 返回**批列表**：每批内并发，批与
批顺序执行；前一批的可见输出对下一批可见。

| 策略 | order 返回 | 语义 |
|---|---|---|
| `Parallel` | `[[a, b, c]]` | 一批全并发，同 tick 内互不见对方刚说的话。 |
| `Sequential` | `[[a], [b], [c]]` | 每个 session 一批，固定顺序。 |
| `Shuffled` | 每个 session 一批，顺序随机 | 模拟"谁先看到群消息"。 |

`ParallelRuntime` / `SequentialRuntime` / `ShuffledRuntime` 是 schedule_policy
的薄预设，不是真的有三种 Runtime 类。

### 4.5 StepPolicy / StopPolicy

- `StepPolicy.deliveries(event, sessions, state)` 决定一个事件投递给哪些
  session。
  - `DeliverToRecipients`：MessageEvent 按 `to` 投递（broadcast 时给除发送者
    外的所有 session）；其他事件全员可见。
  - `TickDriven`：忽略事件流，每 tick 给所有 session 同一个 _TickEvent。
- `StopPolicy.should_stop(state) -> (bool, reason)` 决定何时终止。
  - `StopWhenIdle` / `StopAfterTicks` / `StopAfterEvents` /
    `StopWhenMessageMatches` / `AnyOf`。

### 4.6 PipelineRuntime

固定串行交接链场景：

```python
pipeline = PipelineRuntime([researcher, writer, reviewer])
result = await pipeline.run("写一段产品说明。")
```

它不走 tick loop，也不使用 `StepPolicy` / `SchedulePolicy` / `StopPolicy`。
执行时按顺序调用每个 session 的 `invoke(current)`，并把上一棒的输出作为下
一棒的输入。非末位 agent 自动获得一个 `end(data=...)` 工具——调它就把 data
交给下一棒。

> **为什么不让 PipelineRuntime 用 TickBasedRuntime？** 它不需要事件路由策
> 略，也不需要并发；用 tick loop 反而要造一堆"内部专用"的 Step/Schedule
> Policy。直接独立实现 100 行 + 复用 `BaseRuntime` 的 session 管理更简单。

---

## 5. Event

事件是 AgentSession 之间的通信介质。

```text
AgentSession --MessageEvent--> EventBus --(StepPolicy)--> AgentSession
```

### 5.1 两类用户级事件

- **MessageEvent**：agent-to-agent 通信。`to` 字段直接表达可见性
  （`"*"` 广播 / `frozenset(...)` DM 或子组）。
- **WaitEvent**：Runtime 控制信号。session 的 `on_events` 返回 WaitEvent
  时，**Runtime 直接消费**——把该 session 标记为下一 tick 重新唤醒，不进入
  事件历史、不发布、不路由给其他 session。这避免了"某某等待了"这种系统信
  号污染其他 agent 的上下文。

### 5.2 telemetry 事件

`EventBus` 还会发布以下遥测事件，便于监控与离线分析：

```text
RuntimeStartedEvent / RuntimeFinishedEvent
AgentStartedEvent / AgentFinishedEvent
LLMCalledEvent / LLMRespondedEvent
ToolCalledEvent / ToolResultEvent
```

这些事件**只在 `session.event_bus` 存在时发出**——单 agent 模式下不发，避
免无意义开销。

### 5.3 设计边界

`EventBus` 只做"记录 + 分发 + streaming"，不参与控制流。控制流（停止、跳
过、唤醒）由 Runtime + 各 Policy 决定。Agent / AgentSession 不互相直接调用
方法——所有用户级通信走 MessageEvent，让多 agent 调度可以独立演进。

---

## 6. SharedStore

可选的多 agent 协作状态存储，**不参与 Runtime 主循环**。

```python
store = SharedStore()
store.put("draft", "v1", producer="writer")  # version 1
store.put("draft", "v2", producer="editor")  # version 2

store.get("draft")             # "v2"
store.get("draft", version=1)  # "v1"
store.history("draft")         # [(1, "v1", "writer"), (2, "v2", "editor")]
store.snapshot()               # {"draft": "v2"}
```

线程安全、版本化、只增不删。适合共享草稿、黑板、artifact 索引。

不通过事件总线传——这种状态读写是高频的，用事件会污染历史；用直接 KV 也避
免了"通过广播去同步状态"的糟糕模式。

---

## 7. 数据流速记

### 7.1 单 AgentSession 执行

```text
Agent.run(user_input)
  └─ Agent.create_session()
  └─ Agent.on_session_start(session)        # SandboxAgent 启动沙箱
  └─ Agent.run_session(session, user_input)
       └─ loop: Agent.step(session)         # 直到 done
  └─ Agent.on_session_end(session)          # SandboxAgent 关闭沙箱
  └─ return AgentRunResult.from_session(session)
```

### 7.2 多 AgentSession 协作

```text
Runtime.run(seed_events)
  └─ enter all sessions
  └─ tick loop:
       │ StepPolicy.deliveries(...) -> Deliveries
       │ SchedulePolicy.order(...)  -> [[batch1], [batch2], ...]
       │ for batch:
       │     gather(session.on_events(events) for each session in batch)
       │     produced events:
       │       • WaitEvent  -> Runtime control: 下一 tick 重新唤醒
       │       • 其他 events -> _state.events + bus.publish + 后续 batch 可见
       │ StopPolicy.should_stop(state)
  └─ exit all sessions
  └─ RuntimeResult(state, messages)
```

---

## 8. 命名速查

| 概念 | 类型 | 说明 |
|---|---|---|
| `Agent` / `BaseAgent` | 类 | 单轮 agent + Runtime 看到的最小契约 |
| `ReactAgent` | 类 | ReAct 循环 + 工具调用（多步任务的主入口） |
| `SkillAgent` | 类 | ReactAgent + 按需加载 SKILL.md |
| `SandboxAgent` | 类 | ReactAgent + 沙箱生命周期 |
| `AgentSession` | 类 | agent 的运行实例（分身） |
| `Runtime` / `TickBasedRuntime` | 类 | 多 session 执行环境 |
| `PipelineRuntime` | 类 | 固定串行交接链 |
| `EventBus` | 类 | 事件记录与分发 |
| `MessageEvent` / `WaitEvent` | 类 | 通信原语 / Runtime 控制事件 |
| `StepPolicy` | Protocol | 事件投递策略 |
| `SchedulePolicy` | Protocol | 单 tick 内执行顺序 |
| `StopPolicy` | Protocol | 终止条件 |
| `SharedStore` | 类 | 多 agent 共享 KV 存储 |
| `session_class` | Agent 类属性 | 挂自定义 AgentSession 子类 |
| `session.run` / `step` / `on_events` | 方法 | 单任务跑完 / 单步 / 接 Runtime |
| `runtime.add_agent` / `send` / `run` | 方法 | 添加 session / 注入 seed / 调度循环 |
