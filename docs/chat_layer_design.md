# EasyAgent v2 多 Agent 架构设计文档

> 一份针对多 agent 协作的设计文档，核心是引入 `chat/` 用户层，把 AgentScope 的线性 ergonomics 与 EasyAgent 现有的 runtime/policy 内核以"加法"方式融合，并补足两边都缺的能力（嵌套组合、共享状态、多频道、内置 multi-agent formatter）。
>
> 本文档与 `docs/easyagent_session_runtime_design.md`、`docs/runtime_walkthrough.md` 互补：底层 session/runtime 不动，本文档描述的是其上的新一层。

---

## 0. 目的与非目标

**目的**：用一套统一抽象同时覆盖
- (a) 线性工作流（researcher → writer → editor）
- (b) 群聊 / 群体仿真（多 agent 自由发言）
- (c) 混合协作（消息流 + 共享黑板）
- (d) 跨形态嵌套组合（线性套群聊、群聊套线性）

**非目标**：
- 不取代单 agent 的 ReAct/Skill/Sandbox 实现；
- 不做分布式（agent 跨进程/跨机器）；
- 不做长期持久化（这是 session 层的事）。

---

## 1. 设计原则

| # | 原则 |
|---|---|
| P1 | **Talker 是唯一不可约简的抽象**。LLM agent / 人 / 子系统 / pipeline 都必须实现同一个协议。 |
| P2 | **路由信息写在消息上，不写在订阅器上**。消息自带 `to` 和 `channel`。 |
| P3 | **轮次决策的四种模式同等地位**：调用方决定 / 发言者决定 / 算法决定 / 第三方仲裁。没有"主模式"。 |
| P4 | **组合者必须是 Talker**。任何容器都要能伪装成单个 Talker 嵌进更大容器。这意味着容器必须有 `summarize` 策略——决定对外说什么。 |
| P5 | **EventBus 是观测层，不是传输层**。消息直送，bus 旁路。 |
| P6 | **共享状态与消息流并列**。对话 ≠ 全部协作，黑板是一等公民。 |
| P7 | **`None`/silent 是一等返回值**。"我这次不说话"不是特殊事件。 |
| P8 | **加法不动核**。现有 `BaseAgent`/`Runtime`/`EventBus`/`Memory` 不做破坏性改动；新抽象薄薄装在上面。 |

---

## 2. 六个核心问题与答案

任何多 agent 系统都必须回答下面六个问题。本设计的答案如下：

| 问题 | 设计答案 |
|---|---|
| Q1 消息单位是什么？信里有什么？ | `ChatMessage(sender, content, role, to, channel, reply_to, metadata)` |
| Q2 谁决定下一个谁说话？ | `TurnTaking` 协议，五种内置实现（Conducted / Reactive / Scheduled / Selected / Manual） |
| Q3 谁决定谁能听到？ | `Routing` 协议，三种内置实现（Direct / Broadcast / Pipeline） |
| Q4 何时停止？ | `StopCondition` 协议，可组合（AnyOf/AllOf） |
| Q5 状态在哪？ | 各 Talker 自带 `Memory`（按 channel 索引）+ 容器级 `SharedState` |
| Q6 怎么组合？子系统能否当作更大系统里的一员？ | `Orchestrator` 实现 `Talker` 协议 + `Summarize` 策略决定对外消息 |

---

## 3. 模块布局

```
easyagent/
├── chat/                       # 新增：用户层 API
│   ├── __init__.py
│   ├── message.py              # ChatMessage, Identity
│   ├── talker.py               # Talker 协议, LLMTalker, HumanTalker, RuntimeTalker
│   ├── orchestrator.py         # Orchestrator + TurnContext + _ManualSession
│   ├── strategies/
│   │   ├── routing.py          # Direct / Broadcast / Pipeline
│   │   ├── turn_taking.py      # Conducted / Reactive / Scheduled / Selected / Manual
│   │   ├── stop.py             # AfterAllSpoken / MaxRounds / Idle / OnPredicate / OnSharedKey / AnyOf / AllOf
│   │   └── summarize.py        # LastMessage / Aggregate / ByJudge / FromSharedState / Custom
│   ├── presets.py              # sequential / fanout / debate / chatroom / groupchat
│   ├── formatter.py            # MultiAgentFormatter (内置)
│   └── shared_state.py         # 升级版 SharedStore（订阅 + 并发安全 + bus 桥接）
├── agent/                      # 原有，少量改造（见 §12）
├── runtime/                    # 原有，作为 chat 层底下可选的执行后端
├── events/                     # 原有，承担观测层
└── ...
```

`chat/` 目录是**新加的、独立的、可被旧 API 完全跳过**——这是 P8 的体现。用户继续用 `runtime/` 不会感知到 `chat/`，反之亦然。

---

## 4. 核心数据：`ChatMessage` 与 `Identity`

```python
@dataclass(frozen=True)
class Identity:
    name: str                 # 在 channel 内唯一
    role: str = "agent"       # "agent" | "user" | "system" | "tool" | 自定义
    aliases: frozenset[str] = frozenset()


@dataclass
class ChatMessage:
    sender: Identity
    content: str | list[Block]
    to: Literal["*"] | frozenset[str] = "*"   # 收件人
    channel: str = "default"                  # 房间 / 线程
    role: Literal["user", "assistant", "system", "tool"] = "assistant"
    reply_to: str | None = None               # 因果链
    id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict = field(default_factory=dict)

    @property
    def is_broadcast(self) -> bool:
        return self.to == "*"

    def visible_to(self, name: str) -> bool:
        return self.is_broadcast or name in self.to
```

### 与现有类型的关系

| 类型 | 层 | 责任 |
|---|---|---|
| `model.schema.Message` | LLM API 层 | 用于 `litellm.completion(messages=[...])` 的协议格式 |
| `events.types.MessageEvent` | Bus 事件层 | 在 EventBus 上传播的消息事件 |
| `chat.message.ChatMessage` | **用户对话语义层（新）** | 用户和 Talker 之间收发的对话单位 |

三者各司其职：
- `MultiAgentFormatter` 负责 `list[ChatMessage] → list[Message]`（喂给某个 agent 的 LLM）；
- `chat → bus` 桥接负责 `ChatMessage → MessageEvent`（仅用于观测）；
- 用户在 `chat/` 层看不到底下两类，只接触 `ChatMessage`。

---

## 5. Talker 协议

```python
class Talker(Protocol):
    identity: Identity

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str = "default",
    ) -> ChatMessage | None:
        """处理输入消息（如果有），并产生回复。返回 None 表示这一轮选择沉默（P7）。"""

    async def observe(self, msg: ChatMessage) -> None:
        """只接收消息进入记忆，不产生回复。"""

    async def aclose(self) -> None:
        """可选：资源释放。"""
```

### 三类内置实现

| 实现 | 角色 |
|---|---|
| `LLMTalker` | 包装一个现有 `BaseAgent`（ReactAgent/SkillAgent/SandboxAgent 任一）。`__call__` 把 channel 内 ChatMessage 喂给 agent.run，返回新 ChatMessage。 |
| `HumanTalker` | 通过 input/异步 queue 接 UI 或终端。 |
| `Orchestrator` | 容器（见 §6）。**它本身就是 Talker**——这是 P4 的体现。 |
| `RuntimeTalker` | 包装现有 `BaseRuntime`，让 tick-based runtime 也能当一棒 Talker 嵌入 chat 层。 |

`LLMTalker` 是**改造层**：把已有的 ReactAgent / SkillAgent / SandboxAgent **不改一行**地接入新协议。

---

## 6. Orchestrator：容器

```python
@dataclass
class Orchestrator:
    members: dict[str, Talker]
    routing: Routing
    turn_taking: TurnTaking
    stop: StopCondition
    summarize: Summarize
    identity: Identity = Identity("orchestrator")
    bus: EventBus | None = None
    shared_state: SharedState | None = None

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str = "default",
    ) -> ChatMessage | None:
        ctx = TurnContext(
            members=self.members,
            channel=channel,
            history=[],
            bus=self.bus,
            shared=self.shared_state,
        )
        # 1. seed 消息按 routing 分发给成员
        if msg is not None:
            for tgt in self.routing.targets(msg, ctx):
                await self.members[tgt].observe(msg)
            ctx.history.append(msg)

        # 2. 主循环：turn_taking 选下一个发言者，stop 决定收尾
        while True:
            stop, reason = self.stop.check(ctx)
            if stop:
                ctx.metadata["stop_reason"] = reason
                break

            speaker = await self.turn_taking.next(ctx)
            if speaker is None:
                break

            reply = await self.members[speaker](channel=channel)
            ctx.round_index += 1

            if reply is None:                       # P7: silent
                ctx.idle_rounds += 1
                continue
            ctx.idle_rounds = 0
            ctx.history.append(reply)

            # 3. 回复按 routing 分发（不发回 speaker 自己）
            for tgt in self.routing.targets(reply, ctx):
                if tgt != speaker:
                    await self.members[tgt].observe(reply)

            if self.bus is not None:
                await self.bus.publish(_to_message_event(reply))

        # 4. summarize 决定容器对外说什么（P4）
        return await self.summarize.produce(ctx, self.identity)

    async def observe(self, msg: ChatMessage) -> None:
        """容器作为 Talker 被外层 observe 时，按 routing 分发给成员。"""
        for tgt in self.routing.targets(msg, ctx=None):
            await self.members[tgt].observe(msg)
```

### 五个策略协议

```python
class Routing(Protocol):
    def targets(self, msg: ChatMessage, ctx: TurnContext | None) -> list[str]: ...
# 内置: Direct(by="msg.to") | Broadcast() | Pipeline(order=[...])

class TurnTaking(Protocol):
    async def next(self, ctx: TurnContext) -> str | None: ...
# 内置: Conducted(seq) | Reactive() | Scheduled(RoundRobin|Random|Weighted) | Selected(judge) | Manual()

class StopCondition(Protocol):
    def check(self, ctx: TurnContext) -> tuple[bool, str]: ...
# 内置: AfterAllSpoken | MaxRounds(n) | Idle(grace) | OnPredicate(fn) | OnSharedKey(k) | AnyOf | AllOf

class Summarize(Protocol):
    async def produce(self, ctx: TurnContext, container: Identity) -> ChatMessage | None: ...
# 内置: LastMessage | Aggregate(joiner) | ByJudge(agent) | FromSharedState(key) | Custom(fn)
```

### `TurnContext`

```python
@dataclass
class TurnContext:
    members: dict[str, Talker]
    channel: str
    history: list[ChatMessage]
    round_index: int = 0
    idle_rounds: int = 0
    bus: EventBus | None = None
    shared: SharedState | None = None
    metadata: dict = field(default_factory=dict)
```

**只读地传给策略**。策略不应直接修改成员或历史，只看历史/共享状态做决策。

### Manual 模式

`turn_taking=Manual()` 时 Orchestrator 不主动循环，只在用户 `await member(...)` 时触发路由——等价于 AgentScope 的 MsgHub。这通过同一个 Orchestrator 类加上下文管理器糖实现：

```python
class _ManualSession:
    def __init__(self, orch: Orchestrator):
        self._orch = orch

    async def __aenter__(self):
        self._orch._install_subscribers()       # 给每个 member 装一个 post_reply hook
        if self._orch._announcement is not None:
            await self._orch.broadcast(self._orch._announcement)
        return self

    async def __aexit__(self, *exc):
        self._orch._uninstall_subscribers()

    async def broadcast(self, msg: ChatMessage) -> None:
        for m in self._orch.members.values():
            await m.observe(msg)
```

---

## 7. SharedState（升级 SharedStore）

```python
class SharedState:
    """版本化的并发安全 KV 存储 + 订阅 + bus 桥接。"""

    def put(self, key: str, value: Any, *, producer: str | None = None) -> int: ...
    def get(self, key: str, *, version: int | None = None) -> Any: ...
    def has(self, key: str) -> bool: ...
    def history(self, key: str) -> list[tuple[int, Any, str | None]]: ...
    def keys(self) -> list[str]: ...
    def snapshot(self) -> dict[str, Any]: ...

    # 新增能力
    def subscribe(self, key: str, handler: Callable[[Any], Awaitable[None]]) -> Unsubscribe: ...
    async def wait_for(self, key: str, predicate: Callable[[Any], bool], timeout: float | None = None) -> Any: ...
    def attach_bus(self, bus: EventBus) -> None:
        """写入时自动 publish StateChangedEvent；用于 UI 推流。"""
```

Talker 通过 **`SharedStateTool`** 访问（`put_state` / `get_state` / `wait_for_state`）；不在 Talker 协议层强加，避免对单 agent 场景的污染。

---

## 8. MultiAgentFormatter（内置）

```python
class MultiAgentFormatter:
    """格式化 memory 时，自动把"非本 agent 发的消息"折叠成 user 消息里的
    history 块，用 'name: text' 标注，避免 LLM 把别人的话当成自己说过。

    单 agent 场景（无第三方 sender）自动退化为标准 user/assistant 格式。
    """

    def __init__(self, *, history_tag: str = "history", fold_threshold: int = 1):
        ...

    async def format(self, agent_name: str, msgs: list[ChatMessage]) -> list[Message]:
        # 自己说的       -> role=assistant 正常进 messages
        # 系统消息       -> role=system
        # 他人/外部消息  -> 累积到 buffer，遇到自己消息或末尾时 flush 成一条 user 消息
        #                  内含 <history>name1: text1\nname2: text2\n...</history>
        ...
```

**装载策略**：`LLMTalker` 默认包一个 `MultiAgentFormatter`。它内部检测——若 memory 中只有 `system / user / 自己` 三类 sender，则退化为标准格式（不出现 history 块）。这条直接解决 EasyAgent 当前必须手拼 `[sender 说]` 的痛点。

---

## 9. Presets（用户层薄糖）

```python
def sequential(members, msg=None, *, bus=None) -> ChatMessage:
    """Pipeline + Conducted + AfterAllSpoken + LastMessage"""

def fanout(members, msg, *, gather=True, bus=None) -> list[ChatMessage]:
    """Broadcast + ConductedParallel + AfterOneRound + Collect"""

def debate(members, *, judge, max_rounds, seed=None, bus=None) -> ChatMessage:
    """Broadcast + RoundRobin(members) + (OnPredicate(judge.finished) | MaxRounds) + ByJudge"""

def chatroom(members, *, announcement=None, bus=None) -> _ManualSession:
    """Direct + Manual —— AgentScope MsgHub 等价物"""

def groupchat(members, *, mode="reactive", bus=None) -> Orchestrator:
    """Direct + (Reactive | Random) + Idle + LastMessage"""
```

每个 preset **就是 Orchestrator 配 strategy 的工厂**——没有特殊代码路径。

---

## 10. 与现有 Runtime 的关系

| 场景 | 走哪 |
|---|---|
| 用户写线性 / 群聊 / 嵌套 | `chat/` 层 → Orchestrator |
| 用户要 tick-based 仿真 / 复杂 policy | 现有 `runtime/` 不动 |
| 想把 runtime 当成一棒嵌进 sequential | 给 `BaseRuntime` 加 `__call__(msg) → ChatMessage`，包装成 `RuntimeTalker` |

**两条路径并存，通过 Talker 协议互通**。chat 层是新接口，runtime 层是底层引擎。

---

## 11. EventBus 边界（观测 vs 传输）

| 层 | 传输 | 观测 |
|---|---|---|
| chat | `ChatMessage` 通过 `routing.targets()` 直送 `member.observe()`。**不经过 bus**。 | 路由后 `publish(MessageEvent)`，bus 上有完整流水。 |
| runtime | `MessageEvent` 是 bus 上的事件，本身就是传输载荷（保持现状） | 同上 |
| SharedState | `put()` 同步写值 | 写入时 `publish(StateChangedEvent)` |

UI / 调试通过 bus 订阅，**不感知具体执行后端**。这是干净的层次。

---

## 12. 改造清单（按依赖序）

| # | 改动 | 文件 | 估计 LoC |
|---|---|---|---|
| 1 | `ChatMessage`, `Identity` | `chat/message.py` | 80 |
| 2 | `Talker` 协议 + `LLMTalker`（包装 BaseAgent）+ `HumanTalker` | `chat/talker.py` | 150 |
| 3 | `MultiAgentFormatter` | `chat/formatter.py` | 100 |
| 4 | 五个策略协议 + 默认实现 | `chat/strategies/*.py` | 250 |
| 5 | `Orchestrator` + `TurnContext` + `_ManualSession` | `chat/orchestrator.py` | 180 |
| 6 | `SharedState` + bus 桥 + 订阅 / wait_for | `chat/shared_state.py` | 90 |
| 7 | Presets | `chat/presets.py` | 60 |
| 8 | `BaseAgent.observe()` 公开（包一层 `session.add_message`） | `agent/base.py` | 10 |
| 9 | `BaseRuntime.__call__()` + `RuntimeTalker` | `runtime/base.py`, `chat/talker.py` | 40 |
| 10 | 文档 / example | `docs/`, `examples/` | — |

合计 **~960 LoC**，全部为加法，对现有代码 ≤ 10 行修改。

---

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 概念多 → 入门曲线陡 | 文档与教程从 preset 开始（`sequential` / `chatroom`），不直接暴露 Orchestrator |
| 与现有 `runtime/` 学习路径冲突 | 11 层 examples 收敛：单 agent → chat 层；仿真 / 调度 → runtime 层；嵌套时再讲 RuntimeTalker |
| `ChatMessage` 与 `MessageEvent` 重复 | 边界明确：ChatMessage 是用户层、MessageEvent 是事件层，自动桥接、用户层不感知 |
| `summarize` 是新概念 | 默认 `LastMessage` 直觉成立；只有用户做 debate / aggregation 才需要换 |
| `SharedState` 加并发心智模型 | 仅在用到 `attach_shared_state` 的场景出现，单 agent / 纯对话场景不感知 |

---

## 14. 验收标准

设计成功的标志：
1. **AgentScope `multiagent_conversation/main.py` 用本设计写不超过 30 行**；
2. **EasyAgent `examples/11_group_chat.py` 用本设计 ≤ 50 行**（当前 ~150）；
3. **嵌套场景**：`sequential([planner, debate_team, writer], msg)` 一行可用；
4. **无破坏性改动**：现有所有 examples（00–11）继续跑通。

---

## 15. 配套 Example

参见 `examples/12_unified_collaboration.py` 与文档 `docs/chat_layer_example.md`。该 example 用同一组 agent 演示五种调用形态：

1. `sequential` —— 线性，调用方决定顺序；
2. `chatroom (manual)` —— AgentScope MsgHub 等价物；
3. `debate (selected)` —— 第三方仲裁；
4. **嵌套** —— `sequential([planner, debate_team, writer])`，`debate_team` 是 (3) 整体当一棒；
5. `shared_state` —— 协作不通过消息，通过黑板。

跑完五段后，对比同一组对象在不同形态下的行为差异，可一次性验证 §1 全部 P1–P8 原则与 §2 全部 Q1–Q6 答案。