# EasyAgent Runtime 源码导读

这份文档从一个具体的多智能体通信例子开始，再展开 Runtime 模块如何支撑这个例子。

Runtime 的核心心智模型：

```text
Runtime = sessions + EventBus + RuntimeState + policies
```

Runtime 不管理 agent 模板，也没有 `register_agent()` / `spawn()`。它只管理已经创建出来的 `AgentSession`，并用事件驱动这些 session 通信。

## 1. 一个多智能体通信例子

假设我们要实现一个小团队：

- `planner`：读用户需求，拆任务给 coder
- `coder`：根据 planner 的要求写实现方案
- `reviewer`：检查 coder 的方案，并把 review 结果发回 planner

通信链路是：

```text
user -> planner -> coder -> reviewer -> planner
```

但这个链路不是写死在 Runtime 里的，而是通过 `MessageEvent.to` 表达出来。

### 最小用法

```python
from easyagent.events import MessageEvent
from easyagent.runtime import (
    DeliverToRecipients,
    SequentialRuntime,
    StopAfterTicks,
)

runtime = SequentialRuntime(
    agents={
        "planner": planner_agent,
        "coder": coder_agent,
        "reviewer": reviewer_agent,
    },
    step_policy=DeliverToRecipients(),
    stop_policy=StopAfterTicks(4),
)

result = await runtime.run([
    MessageEvent(
        sender="user",
        to="planner",
        content="实现一个用户登录功能，并让团队协作给出方案。",
    )
])
```

这段代码里最重要的三件事：

1. `agents={...}` 决定 Runtime 里有哪些 session。
2. `MessageEvent(sender="user", to="planner", ...)` 决定第一条消息发给谁。
3. `DeliverToRecipients()` 决定后续消息按 `MessageEvent.to` 投递。

### agent 如何继续通信

Runtime 不要求 planner、coder、reviewer 互相知道对方对象。它们只需要产出事件。

例如 planner 处理用户需求后，可以产出：

```python
MessageEvent(
    sender="planner",
    to="coder",
    content="请设计登录功能的接口、数据流和主要边界情况。",
)
```

coder 可以回复给 reviewer：

```python
MessageEvent(
    sender="coder",
    to="reviewer",
    content="这是实现方案，请 review 安全性和异常处理。",
)
```

reviewer 再发回 planner：

```python
MessageEvent(
    sender="reviewer",
    to="planner",
    content="方案可行，但需要补充 token 过期和重放攻击处理。",
)
```

这些事件可以来自默认 `AgentSession.on_events()`，也可以来自自定义 `AgentSession`。

## 2. 这个例子在 Runtime 里发生了什么

上面的 `SequentialRuntime` 本质上是：

```python
TickBasedRuntime(
    agents={...},
    step_policy=DeliverToRecipients(),
    stop_policy=StopAfterTicks(4),
    schedule_policy=Sequential(),
)
```

运行时流程可以理解成：

```text
seed MessageEvent(user -> planner)
  -> StepPolicy 决定投递给 planner
  -> planner session.on_events(...)
  -> planner 产出 MessageEvent(planner -> coder)
  -> StepPolicy 决定投递给 coder
  -> coder session.on_events(...)
  -> coder 产出 MessageEvent(coder -> reviewer)
  -> StepPolicy 决定投递给 reviewer
  -> reviewer session.on_events(...)
  -> reviewer 产出 MessageEvent(reviewer -> planner)
  -> ...
```

Runtime 只做四件事：

1. 记录和发布事件。
2. 根据 `StepPolicy` 把事件投递给 session。
3. 根据 `SchedulePolicy` 决定同一轮里谁先执行、谁并发。
4. 根据 `StopPolicy` 判断什么时候停止。

## 3. `MessageEvent`：通信原语

agent 之间的用户级通信都通过 `MessageEvent`：

```python
MessageEvent(
    sender="planner",
    to="coder",
    content="请实现登录接口。",
)
```

`to` 直接表达可见性：

- `"*"`：广播给所有 session，发送者自己除外
- `"coder"`：私信给 coder
- `{"coder", "reviewer"}`：发给一个小组

`MessageEvent.__post_init__()` 会把方便写法规范化：

```python
to="coder"              # -> frozenset({"coder"})
to=["coder", "reviewer"] # -> frozenset({"coder", "reviewer"})
```

因此 Runtime 不需要额外的 channel、room 或 topic 对象。最简单的多智能体通信靠 `to` 就够了。

## 4. `BaseRuntime`：管理 sessions

Runtime 里真正被调度的是 `AgentSession`。

构造 Runtime 时：

```python
runtime = SequentialRuntime(
    agents={"planner": planner, "coder": coder, "reviewer": reviewer},
    step_policy=DeliverToRecipients(),
    stop_policy=StopAfterTicks(4),
)
```

`BaseRuntime.__init__()` 会对每个 agent 调用：

```python
runtime.add_agent(name, agent)
```

`add_agent()` 做的事很少：

```python
session = agent.create_session()
session.session_id = name
session.agent = agent
session.event_bus = runtime.bus
runtime.sessions[name] = session
```

然后安装 `StopEvent` listener，并刷新 `state.agent_ids`。

最终 Runtime 只维护一张核心表：

```python
self.sessions: dict[AgentId, AgentSession]
```

这也是为什么多个 worker 不需要模板注册机制：

```python
runtime = SequentialRuntime(
    agents={
        "worker_1": WorkerAgent(...),
        "worker_2": WorkerAgent(...),
        "worker_3": WorkerAgent(...),
    },
    step_policy=DeliverToRecipients(),
    stop_policy=StopAfterTicks(3),
)
```

## 5. `StepPolicy`：消息交给谁

在例子里，我们使用：

```python
step_policy=DeliverToRecipients()
```

它的逻辑是：

```text
如果是 MessageEvent:
  to == "*"     -> 投递给所有 session，排除 sender
  to == {...}   -> 投递给可见目标，排除 sender

如果不是 MessageEvent:
  默认投递给所有 session
```

对应代码形态：

```python
deliveries(event, sessions, state) -> list[(session_id, event)]
```

比如当前 Runtime 有：

```python
sessions = {
    "planner": planner_session,
    "coder": coder_session,
    "reviewer": reviewer_session,
}
```

当事件是：

```python
MessageEvent(sender="planner", to="coder", content="...")
```

`DeliverToRecipients.deliveries()` 返回：

```python
[("coder", event)]
```

这就是 Runtime 后续会调用 `coder_session.on_events([event])` 的原因。

## 6. `SchedulePolicy`：同一轮谁先执行

如果一个事件同时投递给多个 session，就需要决定执行顺序。

比如：

```python
MessageEvent(sender="user", to="*", content="大家各自给出意见")
```

`DeliverToRecipients()` 会把它投递给 planner、coder、reviewer。

`SchedulePolicy` 决定这三个 session 怎么执行：

```python
Parallel().order(["planner", "coder", "reviewer"], state)
# [["planner", "coder", "reviewer"]]

Sequential().order(["planner", "coder", "reviewer"], state)
# [["planner"], ["coder"], ["reviewer"]]

Shuffled().order(["planner", "coder", "reviewer"], state)
# 例如 [["coder"], ["planner"], ["reviewer"]]
```

区别：

- `Parallel`：同一批并发执行，彼此看不到这一批内对方刚产出的消息
- `Sequential`：按顺序执行，后面的 session 可以看到前面 session 刚产出的可见消息
- `Shuffled`：每个 tick 随机顺序，适合模拟群聊里“谁先看到消息”

`SequentialRuntime` / `ParallelRuntime` / `ShuffledRuntime` 只是帮你固定了 `schedule_policy`。

## 7. `StopPolicy`：什么时候结束

例子里用了：

```python
stop_policy=StopAfterTicks(4)
```

这表示最多跑 4 个 tick。

常用停止策略：

- `StopWhenIdle(grace_steps=1)`：没有新事件一段时间后停止
- `StopAfterTicks(max_ticks)`：到 tick 上限停止
- `StopAfterEvents(max_events)`：到事件数上限停止
- `StopWhenMessageMatches(predicate)`：某条消息满足条件时停止
- `AnyOf([...])`：任一策略触发就停止

更实际的组合：

```python
from easyagent.runtime import AnyOf, StopAfterTicks, StopWhenIdle

stop_policy = AnyOf([
    StopWhenIdle(grace_steps=1),
    StopAfterTicks(8),
])
```

这样可以避免 agent 已经不再产出消息时还空跑，也能防止无限循环。

## 8. `TickBasedRuntime` 主循环

现在把例子放回源码层面。

`runtime.run(seed_events)` 做的第一件事是合并两类初始事件：

- `runtime.send(event)` 暂存的事件
- `run(seed_events=[...])` 传入的事件

然后发布 `RuntimeStartedEvent`，进入所有 session 生命周期，并调用 `_run_tick_loop()`。

核心循环简化后是：

```text
pending = seed events 经过 StepPolicy 路由后的 deliveries

while True:
  state.tick += 1

  if stop_policy.should_stop(state):
      break

  next_pending = []

  if pending:
      produced = _run_batch(pending)
      next_pending += _handle_produced_events(produced)

  tick_deliveries = step_policy.deliveries_on_tick(...)  # 如果策略提供
  if tick_deliveries:
      produced = _run_batch(tick_deliveries)
      next_pending += _handle_produced_events(produced)

  state.idle_steps = 0 if next_pending else state.idle_steps + 1
  pending = next_pending
```

这里有三个关键 helper。

### `_record_and_route()`

普通事件都会走这里：

```python
self._state.events.append(event)
await self._bus.publish(event)
return self._step_policy.deliveries(event, self.sessions, self._state)
```

也就是：记录、发布、再路由。

### `_handle_produced_events()`

session 产出的事件先经过分类：

- `WaitEvent`：Runtime 内部消费，不记录、不发布，只放进下一轮 pending
- 其他事件：调用 `_record_and_route()`

如果消息发给不存在的 session，会调用：

```python
await self.on_undeliverable(event)
```

默认返回 `None`，也就是丢弃。子类可以 override 这个方法做 human-in-the-loop 或外部转发。

### `_run_batch()`

`_run_batch(deliveries)` 负责执行一批投递：

1. 按 session id 聚合 deliveries
2. 调用 `schedule_policy.order()`
3. 遍历 batch
4. 同一个 batch 内用 `asyncio.gather()` 并发调用 `_call_agent()`
5. batch 和 batch 之间串行
6. 后面的 batch 可以看到前面 batch 产出的可见 `MessageEvent`

可见消息过滤规则：

```python
isinstance(event, MessageEvent)
and event.sender != agent_id
and event.visible_to(agent_id)
```

## 9. 自定义通信方式

如果 `MessageEvent.to` 不够，可以自定义 `StepPolicy`。

例如：所有 coder 消息都强制送 reviewer，不管 `to` 写什么：

```python
class CodeReviewPolicy:
    def deliveries(self, event, sessions, state):
        if isinstance(event, MessageEvent) and event.sender == "coder":
            if "reviewer" in sessions:
                return [("reviewer", event)]
        return DeliverToRecipients().deliveries(event, sessions, state)
```

然后：

```python
runtime = SequentialRuntime(
    agents={
        "planner": planner,
        "coder": coder,
        "reviewer": reviewer,
    },
    step_policy=CodeReviewPolicy(),
    stop_policy=StopAfterTicks(5),
)
```

如果希望 agent 即使没人发消息也能每轮主动思考，可以用 `TickDriven()`：

```python
runtime = ShuffledRuntime(
    agents=agents,
    step_policy=TickDriven(),
    stop_policy=StopAfterTicks(10),
)
```

`TickDriven` 会在每个 tick 给所有 session 发一个内部 `_TickEvent`。

## 10. `PipelineRuntime`：固定链路的另一种实现

如果你的场景就是固定顺序：

```text
researcher -> writer -> reviewer
```

不需要自由通信、不需要广播、不需要调度策略，那就用 `PipelineRuntime`：

```python
pipeline = PipelineRuntime([researcher, writer, reviewer])
result = await pipeline.run("写一段产品说明")
```

Pipeline 不走 tick loop，也不使用 `StepPolicy` / `SchedulePolicy` / `StopPolicy`。

它的执行就是：

```text
current = user_input

for sid in chain:
    current = await session.invoke(current)
    publish MessageEvent(sender=sid, to="*", content=current)
```

它适合“上一步输出就是下一步输入”的场景。只要 agent 之间需要动态通信，就回到 `TickBasedRuntime`。

## 11. `SharedStore`

`SharedStore` 是可选的共享状态，不参与 Runtime 主循环。

它是线程安全、只增不删的版本化 key-value store：

```python
store = SharedStore()

store.put("draft", "v1", producer="writer")  # version 1
store.put("draft", "v2", producer="editor")  # version 2

store.get("draft")             # "v2"
store.get("draft", version=1)  # "v1"
store.history("draft")         # [(1, "v1", "writer"), (2, "v2", "editor")]
store.snapshot()               # {"draft": "v2"}
```

它适合共享草稿、黑板、artifact 索引等协作状态。

## 12. 总结

回到最开始的 planner/coder/reviewer 例子：

```text
user -> planner -> coder -> reviewer -> planner
```

EasyAgent Runtime 的实现方式是：

1. `BaseRuntime` 把 agent 转成 `runtime.sessions`。
2. 用户或 agent 产出 `MessageEvent`。
3. `StepPolicy` 根据事件决定投递给谁。
4. `SchedulePolicy` 决定同一轮如何执行这些 session。
5. session 处理事件并产出新事件。
6. Runtime 记录、发布、再路由这些新事件。
7. `StopPolicy` 决定循环何时停止。

一句话：Runtime 不写死通信流程；通信流程由 `MessageEvent.to` 和 `StepPolicy` 共同决定。
