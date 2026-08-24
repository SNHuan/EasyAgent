# EasyAgent Architecture

EasyAgent 是一个分层 SDK。每一层只解决一个问题，可以学完一层再进入下一层。

```text
Model
  -> Memory + Context
  -> Agent  (Agent / ReactAgent + optional skills / sandbox / hooks)
  -> Tool / Skill / Sandbox / Hook
  -> AgentSession + AgentCheckpoint
  -> Entity + World + Schedule → Runtime            ← 多 agent
  -> Presets: sequential / fanout / debate / chatroom / groupchat
```

整个 SDK 围绕**两条主线**：

```text
单 agent 主线：  Model + Memory + Context + Tool + AgentSession  →  ReactAgent（可组合 skills / sandbox）
多 agent 主线：  Entity (协议)  +  World (环境)  +  Schedule (调度)  →  Runtime (循环)
```

> 心智模型：
> - **Agent** 是定义；**AgentSession** 是实例；
> - **Entity** 是"谁能行动"的统一抽象；**World** 决定 Entity 感知什么、行动如何生效；**Schedule** 决定谁下一个行动；
> - **Runtime** 把三者串成 perceive-act-apply 循环。

## 1. Model

模型层是 SDK 中唯一直接和 LLM provider 通信的层。

- `BaseLLM` 定义适配契约。
- `LiteLLMModel` 通过 LiteLLM 实现该契约。
- `Message`、`ToolCall`、`LLMResponse` 定义 SDK 的消息 schema。

`Message` 带一个可选的 `name` 字段——多 agent 场景中用它在 prompt 里区分自己和他人，单 agent 场景下可忽略。

## 2. Memory and Context

Memory 存对话状态。Context 决定每次发给模型的是哪一部分。

- `BaseMemory` 存消息。
- `InMemoryMemory` 是默认的进程内实现。
- `BaseContext` 把 memory 渲染成模型消息。
- `FullContext`、`SlidingWindowContext`、`SummaryContext` 是单 agent 的渲染策略。
- `MultiAgentFormatter`（`easyagent/context/multi_agent.py`）是多 agent 场景的渲染策略——把别人的发言折叠成 user 消息里的 `<history>` 块，避免 LLM 把别人的话当成自己说过的。

## 3. Agent

`Agent` 是**可复用配置**——它描述"这个 agent 是什么"，但**不直接代表某次正在运行的对话或任务**。

```text
Agent = Model + MemoryFactory + ContextStrategy + HookManager + (子类引入的 tools/skills/sandbox) + Instructions
```

SDK 提供四个具体 agent 类，通过继承叠加能力：

| 类 | 行为 |
|---|---|
| `Agent` | 单轮模型调用。一次 `run()` = 一次 LLM 调用。 |
| `ReactAgent(Agent)` | ReAct 循环，并可组合 tools、skills 和 sandbox。 |
| `SkillAgent(ReactAgent)` | 便利包装；内部仍使用 ReactAgent 的 skills 实现。 |
| `SandboxAgent(ReactAgent)` | 便利包装；内部仍使用 ReactAgent 的 sandbox 实现。 |

**Agent 不持有运行态**：当前对话 memory、当前任务状态、当前 sandbox 实例等都不属于 Agent，而属于 AgentSession。`Agent` 只持有 `_memory_factory` 与 `_context_factory`，它们在 `create_session()` 时被克隆为该 session 独立的实例。

`ReactRunEngine` 是 `ReactAgent` 内部的执行模块。它通过一个
`execute_step(session, system_prompt, stream=...)` 接口隐藏一次完整 ReAct
状态转换：模型调用、流式 chunk、响应处理、工具执行顺序、Event、Hook、memory
写入和 Stop 边界。它是内部 seam，不增加根包公共接口。

## 4. Tool / Skill / Sandbox

三个相关但不同层的概念：

- **Tool**：模型可见的可调用函数；通过 `ToolContext` 显式获取 session、sandbox、
  event bus 和 metadata，并返回结构化 `ToolResult`。新接口用
  `context_aware = True` 显式声明，避免通过函数参数名猜测；旧式
  `execute(**kwargs)` 工具由 ToolManager 的兼容 Adapter 承接。
- **Skill**：一个目录包，包含必需的 `SKILL.md` 入口文件，以及可选的 `references/`、`templates/`、`assets/`、`scripts/`。
- **Sandbox**：工具执行所在的环境（`LocalSandbox` 或 `DockerSandbox`）。

需要沙箱的工具（`bash` / `write_file` / `read_file`）从 `session.sandbox` 直接读取，不再通过字符串 key 索引。
配置字典或工厂会为每个 Session 创建独立 sandbox；直接传入已有实例时，
ReactAgent 通过串行 lease 保证并发 Session 不会互相 stop。

## 5. AgentSession

`AgentSession` 是某个 Agent 在某次执行中的**运行实例**——也就是 agent 的"分身"。

```text
AgentSession = Agent 引用 + Memory + 渲染状态 + Resources + 当前任务状态
```

每个 session 都有自己的：

- `session_id`、对所属 `agent` 的引用；
- `memory`、`context`、`enabled_tools`、`loaded_skills`；
- `sandbox`、`resources`；
- `event_bus`、`metadata`、`status`、`iteration_count`、`final_output`、`loop_state`、`loop_steps`；
- 可选的 `checkpoint_store`，用于保存安全步骤边界上的可序列化快照。

### 执行入口

```python
class AgentSession:
    async def run(self, user_input) -> str:
        """追加输入并执行完整生命周期直到完成。Agent.run 委托给它。"""

    async def run_prepared(self) -> str:
        """对 memory 中已准备好的消息执行同一生命周期。LLMEntity 使用它。"""

    async def step(self) -> LoopStepResult:
        """低层增量入口；普通调用方不应绕过 run 生命周期。"""
```

- `run` / `run_prepared` 统一负责 setup、执行、cleanup、终态与生命周期事件；
  `step` 只是低层增量入口。

### 5.1 Event 与 Hook：观测平面和控制平面

两者不能混用：

| 机制 | 用途 | 失败语义 | 返回值 |
|---|---|---|---|
| `EventBus` | tracing、日志、UI、外部观察 | 记录日志并隔离，不改变执行结果 | 忽略 |
| `HookManager` | 策略、审批、参数改写、结果改写 | 向上传播并终止当前执行 | 由具体 Hook 组合 |

`EventBus.publish()` 仍然等待订阅者完成，以保持事件顺序，但订阅者只是被动观察者。
如果一个观察者写 trace 失败，其他观察者仍会收到事件，Agent 的业务结果也不受影响。

Hook 属于 Agent 的可复用配置，并按注册顺序串行执行。每个 Hook 类型自己定义返回值
如何折叠到下一位处理器看到的状态：

```text
ToolCalledEvent（被动观察）
  -> BeforeToolCallHook
       -> 可替换 arguments
       -> 可 block，生成错误 ToolResult
  -> ToolManager.execute（未被 block 时）
  -> AfterToolCallHook
       -> 可替换 ToolResult
  -> ToolResultEvent（被动观察）
```

Hook 处理器抛出的异常不会被隔离，因为审批或安全策略不可用时继续执行会掩盖控制
失败。需要优雅结束当前 Session 时，控制方直接调用
`AgentSession.request_stop(reason=..., data=...)`；`StopEvent` 只保留为可选的被动
通知，不再承担停止执行的职责。

### 5.2 Checkpoint：执行状态持久化边界

`AgentCheckpoint` 是 `AgentSession` 状态的可序列化值对象；
`CheckpointStore` 只负责保存和按 `session_id` 读取最新快照。它与用于展示和
查询历史的 `TraceStore` 是两个独立概念。

快照包含 messages、loop steps/state、iteration、final output、启用的
tools/skills 和 metadata。它不包含 Agent 定义本身，也不包含 sandbox、
resources、EventBus 或正在执行的工具副作用。托管的 `run()` / `stream()` 循环
只在每个步骤完成后自动保存，并在 cleanup 完成后写入最终 `completed` 快照；
手动调用 `create_checkpoint()` / `save_checkpoint()` 时，安全边界由调用方负责。

Checkpoint 是执行正确性边界，不是被动观测：配置 store 后，状态不可 JSON
序列化或保存失败会令本次执行失败。当前实现 capture/save/load/restore/resume；
恢复 Session 状态和恢复执行是两个不同动作。

内置两个 Adapter：

| Adapter | 定位 |
|---|---|
| `MemoryCheckpointStore` | 测试、Notebook 和单进程临时状态 |
| `SQLiteCheckpointStore` | 跨进程持久化每个 Session 的最新快照；构造时不做 I/O，异步 `save/load` 把数据库操作移出 event loop |

`AgentCheckpoint.schema_version` 是存储兼容性边界。未知版本由
`UnsupportedCheckpointVersionError` 明确拒绝，不尝试静默降级或猜测字段。

`Agent.check_checkpoint(checkpoint)` 提供只读的恢复前预检，返回
`CheckpointCompatibilityReport`。基础 Agent 检查稳定身份与非空名称；
`ReactAgent` 继续检查 checkpoint 启用过的 tools 当前是否已注册、加载过的
skills 当前是否在 Agent 的 `skills=[...]` 中显式声明。报告一次汇总全部阻断
原因，不创建 Session、不修改 checkpoint、不执行工具，也不扫描或读取能力目录。
Skill 文件的加载与内容校验仍属于实际执行阶段。

`checkpoint_identity` 默认使用 Agent 类的完整限定名，也允许应用显式指定
稳定值，以跨越类名或模块重命名。`agent_type` 仅保留为诊断展示字段，不作为
兼容性锚点。`CheckpointCompatibilityIssue.code` 是程序分支契约；
`report.errors` 只是供日志和界面使用的消息视图。`report.compatible` 只表示
当前 Agent 能解释快照，不表示已经支持恢复执行。

恢复 Module 只有两个顺序明确的 Interface：

1. `Agent.restore_session(checkpoint)` 先执行兼容性预检，再通过 Agent 的
   Session 工厂创建实例，并恢复 messages、status、iteration、loop steps/state、
   final output、tools/skills 和 metadata。
2. `await session.resume()` 显式进入正常 lifecycle，从已恢复的安全步骤继续。

恢复值与 checkpoint 隔离；context 和 memory 仍使用当前 Agent 的工厂，但
memory 工厂自带的初始消息会先被清空，再由 checkpoint 消息完整替换。
sandbox、resources、EventBus、停止请求以及执行中的副作用不会被恢复，整个过程
也不会进入 lifecycle、调用模型、工具、Hook 或技能加载。只有第二步 `resume()`
才通过 `on_session_start/end` 重建并清理 lifecycle 资源。

不兼容由 `IncompatibleCheckpointError` 返回完整的结构化报告；消息或循环状态
无法解码、Session ID 为空或状态不满足 JSON 持久化契约时抛出
`InvalidCheckpointStateError`。恢复成功只得到静态 Session，不会隐式继续运行。

`resume()` 只接受由 checkpoint 恢复、且 checkpoint 状态为 `running` 的
Session。它不清空 iteration、messages、loop steps/state：最后一步为
`CONTINUE` 时从下一步继续；最后一步已经 terminal 时只补齐 lifecycle 和最终
`completed` checkpoint，不重复模型或工具调用。resume 标记会在第一个 await
之前单次消费，执行失败或并发重复调用都必须重新加载最后一个安全 checkpoint。
非法调用抛出 `SessionNotResumableError`，reason 是 `not_restored`、
`checkpoint_not_running` 或 `already_resumed`。首版只提供非流式 resume。

## 6. 多 Agent：Entity-World-Schedule 架构

多 agent 层围绕三个**正交协议**展开——换任何一个都不影响另外两个。

### 6.1 Entity 协议

```python
@runtime_checkable
class Entity(Protocol):
    @property
    def id(self) -> str: ...
    async def act(self, perception: Perception) -> Action | None: ...
```

Entity 是"谁能行动"的统一抽象。任何满足 `id` + `act()` 的对象都是 Entity。

三种内置实现：

| 实现 | 角色 |
|---|---|
| `LLMEntity` | 包装现有 Agent。每次 `act()` 按原顺序从 Perception 重建 memory，再委托 `AgentSession.run_prepared()`，因此与直接调用共享同一生命周期。 |
| `TeamEntity` | 把一个完整的 `Runtime` 包装成单个 Entity——嵌套的关键。`act()` 用 perception 里的最后一条消息 seed 内层 Runtime，运行到结束，返回内层的最终发言。 |
| `HumanEntity` | 通过 `asyncio.Queue` 或 callback 接受人类输入。 |

### 6.2 Perception 和 Action

**Perception** 是 Entity 在当前 tick 看到的世界快照，由 World 构造：

```python
@dataclass(frozen=True)
class Perception:
    entity_id: str
    tick: int
    slices: tuple[PerceptionSlice, ...]

    def of_type(self, cls: type[T]) -> T | None: ...
    def all_of_type(self, cls: type[T]) -> tuple[T, ...]: ...
```

World 不同，Perception 里的 slice 就不同：

| Slice | 来源 World | 内容 |
|---|---|---|
| `MessagesSlice` | `ConversationWorld` / `PipelineWorld` | `messages: tuple[ChatMessage, ...]` |
| `SpatialSlice` | `SpatialWorld` | `position: tuple[int, int]`、`nearby: tuple[str, ...]` |
| `StateSlice` | `StatefulWorld` | `snapshot: tuple[tuple[str, Any], ...]` |

**Action** 是 Entity 决定做什么，由 `act()` 返回：

| Action | 效果 |
|---|---|
| `Speak(content, to)` | 说话，`to="*"` 广播，`to=frozenset(...)` 私聊 |
| `Move(target)` | 移动到新位置（SpatialWorld） |
| `SetState(key, value)` | 写入黑板（StatefulWorld） |
| `Silent()` | 什么都不做 |
| `Composite(actions)` | 一个 tick 内执行多个 action |

### 6.3 World 协议

```python
@runtime_checkable
class World(Protocol):
    def observe(self, entity_id: str) -> Perception: ...
    def apply(self, entity_id: str, action: Action) -> None: ...
    def seed(self, content: str, *, sender: str = "user") -> None: ...
```

World 决定 Entity 感知什么、行动如何生效。换一个 World 就得到完全不同的行为——同一个 Entity 和 Schedule 可以用在对话场景，也可以用在空间探索场景。

四种内置实现：

| World | 用途 |
|---|---|
| `ConversationWorld` | 扁平聊天历史，所有 Entity 看到完整对话。 |
| `PipelineWorld(order)` | 流水线：entity N 只看到 seed + entity N-1 的输出。 |
| `SpatialWorld(grid, listen_radius)` | 2D 网格，距离限制感知。`Speak` 只有 radius 内的 Entity 能听到，`Move` 改变位置。 |
| `StatefulWorld(inner)` | 装饰器：给任何 World 的 Perception 加上 `StateSlice`，处理 `SetState` action。配合 `SharedState` 使用。 |

### 6.4 Schedule 协议

```python
@runtime_checkable
class Schedule(Protocol):
    def next(self, state: LoopState) -> list[str] | None: ...
```

返回下一个 tick 应该行动的 entity ID 列表，返回 `None` 表示结束。

八种内置实现：

| Schedule | 行为 |
|---|---|
| `TakeTurns(order)` | 固定顺序，每个说一次，全部说完返回 None |
| `RoundRobin(ids)` | 循环轮流，每 tick 一个，永不停止 |
| `AllParallel(ids)` | 每 tick 所有人同时行动 |
| `RandomOrder(ids)` | 每 tick 一个，随机选 |
| `Reactive` | 上一条 Speak 的 `to` 里提到的 entity 下一个说话 |
| `MaxTicks(inner, n)` | 包装另一个 Schedule，最多 n 个 tick |
| `UntilIdle(inner, grace)` | 包装另一个 Schedule，连续 grace 轮 Silent 后停止 |
| `UntilPredicate(inner, predicate)` | 包装另一个 Schedule，谓词为真时停止 |

### 6.5 Runtime

```python
class Runtime:
    def __init__(self, world, entities, schedule, bus=None): ...
    async def run(self, seed, *, sender="user") -> RuntimeResult: ...
```

Runtime 是胶水——它不包含业务逻辑，只执行 perceive-act-apply 循环：

```text
world.seed(seed, sender)
while (active := schedule.next(state)) is not None:
    for entity_id in active:
        perception = world.observe(entity_id)
        action = await entities[entity_id].act(perception)
        if action:
            world.apply(entity_id, action)    # Composite → 逐个 apply
        state.action_log.append((entity_id, action or Silent()))
    state.tick += 1
return RuntimeResult(...)
```

可选传入 `EventBus` 用于观测（每个 `Speak` action 发 `MessageEvent`）。

### 6.6 SharedState：黑板协作

不是所有协作都该走对话。共编一份文档、投票、累积评分、等待外部信号——这些场景把状态硬塞进消息里很别扭。

`SharedState` 提供版本化的并发安全 KV，配合 `StatefulWorld` 和 `UntilPredicate`，Entity 可以通过 `SetState` action 写黑板，通过 `StateSlice` 读黑板。

```python
shared = SharedState()
world = StatefulWorld(inner=ConversationWorld(), shared=shared)

# Entity 的 act() 里：
return SetState(key="draft", value="...")   # 写黑板
state_slice = perception.of_type(StateSlice) # 读黑板
```

### 6.7 五个 Preset

```python
sequential([e1, e2, e3], "go")              # 流水线
fanout([e1, e2, e3], "go")                  # 同时丢给所有人
debate([e1, e2], rounds=3, seed="go")       # 多轮辩论，可选 judge
chatroom([e1, e2])                          # 手动控制每一轮
groupchat([e1, e2, e3], rounds=5, seed="go") # LLM 自己决定下一棒
```

每个 preset 都只是 `Runtime(world=..., schedule=...)` 的薄工厂——没有特殊代码路径。

### 6.8 嵌套

`TeamEntity` 把一个完整的 Runtime 包装成单个 Entity，所以任何 Runtime 都可以嵌进另一个 Runtime 当一棒：

```python
# 内层：debate Runtime
debate_runtime = Runtime(world=..., entities={"alice": alice, "bob": bob}, schedule=...)
debate_team = TeamEntity("debate_team", debate_runtime)

# 外层：sequential pipeline
result = await sequential([planner, debate_team, writer], "...")
```

writer 只看到 debate_team 的一句结论，看不到 alice/bob 的原话——这就是 `TeamEntity` 提供的封装边界。

## 7. 为什么是三个正交协议

架构解耦成 Entity、World、Schedule 三个正交轴，是因为**它们的变化维度完全独立**：

| 变化维度 | 例子 |
|---|---|
| 换 Entity | 同一个 ConversationWorld + RoundRobin，把 LLMEntity 换成 HumanEntity 就能让人参与 |
| 换 World | 同一个 Entity + Schedule，把 ConversationWorld 换成 SpatialWorld 就从对话变成空间探索 |
| 换 Schedule | 同一个 Entity + World，把 RoundRobin 换成 Reactive 就从固定轮次变成 LLM 自选下一棒 |

这种正交性意味着 N 种 Entity × M 种 World × K 种 Schedule = N×M×K 种组合，而不是 N×M×K 种实现。

## 8. 数据流

### 单 Agent 执行

```text
Agent.run(user_input)
  └─ Agent.create_session()
  └─ AgentSession.run(user_input)
       ├─ Agent.on_session_start(session)
       ├─ Agent.run_session(session, user_input)
       │    └─ loop: ReactRunEngine.execute_step(stream=False)
       │         └─ 完成步骤 → CheckpointStore.save(AgentCheckpoint)
       ├─ Agent.on_session_end(session)
       └─ 完成状态 → 最终 checkpoint 与生命周期 Event
  └─ return AgentRunResult.from_session(session)

Agent.stream(user_input)
  └─ AgentSession.stream(user_input)
       └─ loop: ReactRunEngine.execute_step(stream=True)
            ├─ 实时产生 chunk
            ├─ 使用与 run() 相同的响应、工具、Hook、Event 和 Stop 转换
            └─ 在相同的安全步骤边界保存 checkpoint
```

### 多 Agent：perceive-act-apply 循环

```text
Runtime.run(seed)
  └─ world.seed(seed, sender="user")
  └─ tick loop:
       │ schedule.next(state) → active entity IDs (or None → stop)
       │ for each entity_id in active:
       │     perception = world.observe(entity_id)
       │     action = await entity.act(perception)
       │     if action: world.apply(entity_id, action)
       │     state.action_log.append((entity_id, action))
       │ state.tick += 1
  └─ RuntimeResult(actions, ticks)
```

### LLMEntity 内部（Agent ↔ Perception 桥接）

```text
LLMEntity.act(perception)
  └─ 从 perception 取 MessagesSlice
  └─ 清空 agent memory
  └─ 重建 memory：自己的消息 → assistant，别人的 → user（带 name 前缀）
  └─ 驱动 agent 的 step 循环
  └─ 取 final_output → Speak(content=...)
```

## 9. Public API

```python
# 单 agent + 工具
from easyagent import (
    Agent, ReactAgent, SkillAgent, SandboxAgent,
    AgentSession, AgentRunResult, SessionNotResumableError,
    AgentCheckpoint, CheckpointCompatibilityIssue,
    CheckpointCompatibilityReport, CheckpointStore,
    IncompatibleCheckpointError, InvalidCheckpointStateError,
    MemoryCheckpointStore, SQLiteCheckpointStore,
    UnsupportedCheckpointVersionError,
    LiteLLMModel, Message,
    Tool, ToolContext, ToolResult, ToolManager, SkillManager, register_tool,
    EventBus, MessageEvent,
    HookManager, BeforeToolCallHook, BeforeToolCallResult, AfterToolCallHook,
    ExternalRunRequest,
)

# 多 agent：Entity-World-Schedule
from easyagent import (
    # 协议
    Entity, World, Schedule, Runtime, RuntimeResult,
    # 感知与动作
    Perception, Speak, Silent, ChatMessage,
    # Entity 实现
    LLMEntity, TeamEntity, HumanEntity,
    # World 实现
    ConversationWorld, PipelineWorld, SpatialWorld, StatefulWorld, SharedState,
    # Schedule 实现
    TakeTurns, RoundRobin, AllParallel, MaxTicks, UntilIdle, Reactive,
    # 预设
    sequential, fanout, debate, chatroom, groupchat,
)
```

## 10. 命名速查

| 概念 | 类型 | 层 | 说明 |
|---|---|---|---|
| `Agent` / `BaseAgent` | 类 | agent | 单 agent 定义 + 最小契约 |
| `ReactAgent` | 类 | agent | 可组合工具、技能和沙箱的 ReAct agent |
| `SkillAgent` / `SandboxAgent` | 类 | agent | ReactAgent 的便利包装 |
| `AgentSession` | 类 | agent | agent 的运行实例（分身） |
| `SessionNotResumableError` | 异常 | agent | Session 不满足显式单次续跑条件 |
| `ReactRunEngine` | 内部类 | agent | run/stream 共用的单步 ReAct 状态转换 |
| `AgentCheckpoint` | 值对象 | checkpoint | 安全步骤边界上的可序列化 Session 状态 |
| `CheckpointCompatibilityIssue` | 值对象 | checkpoint | 带稳定问题码和结构化细节的单个兼容性问题 |
| `CheckpointCompatibilityReport` | 值对象 | checkpoint | Agent 对 checkpoint 的只读兼容性预检结果 |
| `IncompatibleCheckpointError` | 异常 | checkpoint | Session 恢复前兼容性检查失败，携带完整报告 |
| `InvalidCheckpointStateError` | 异常 | checkpoint | checkpoint 内容无法解码为 Session 状态 |
| `CheckpointStore` | Protocol | checkpoint | 保存/读取最新执行快照的端口 |
| `MemoryCheckpointStore` | 类 | checkpoint | 进程内 checkpoint Adapter |
| `SQLiteCheckpointStore` | 类 | checkpoint | 持久化 checkpoint Adapter |
| **`Entity`** | Protocol | **core** | 「谁能行动」的统一抽象 |
| `LLMEntity` / `TeamEntity` / `HumanEntity` | 类 | entities | Entity 的具体实现 |
| **`World`** | Protocol | **core** | Entity 感知和作用的环境 |
| `ConversationWorld` / `PipelineWorld` / `SpatialWorld` / `StatefulWorld` | 类 | worlds | World 的具体实现 |
| **`Schedule`** | Protocol | **core** | 决定谁下一个行动 |
| `TakeTurns` / `RoundRobin` / `AllParallel` / `Reactive` / `MaxTicks` / `UntilIdle` | 类 | core | Schedule 的具体实现 |
| **`Runtime`** | 类 | **core** | perceive-act-apply 循环 |
| `Perception` / `PerceptionSlice` | 类 | core | Entity 在当前 tick 看到的世界快照 |
| `Action` / `Speak` / `Move` / `SetState` / `Silent` / `Composite` | 类 | core | Entity 决定做什么 |
| `ChatMessage` | 类 | core | 多 agent 消息原语 |
| `SharedState` | 类 | worlds | 黑板协作原语 |
| `MultiAgentFormatter` | 类 | context | 多 agent prompt 渲染 |
| `sequential` / `fanout` / `chatroom` / `groupchat` / `debate` | 函数 | presets | preset 工厂 |
| `EventBus` | 类 | events | 被动事件记录与分发；观察者失败不改变执行 |
| `HookManager` | 类 | hooks | 按顺序执行可阻断、可改写的控制逻辑 |
| `BeforeToolCallHook` / `AfterToolCallHook` | 类 | hooks | 工具调用前后的控制点 |
| `MessageEvent` | 类 | events | 通信观测事件 |
| `RuntimeResult` | 类 | core | Runtime 执行结果 |
