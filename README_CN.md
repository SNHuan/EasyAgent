# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

[English](README.md) | 中文

EasyAgent 是一个轻量级 Agent SDK，核心设计是分层组合。项目希望让你能逐步学习
Agent 的设计：从最直接的模型调用开始，依次加入记忆、上下文、ReAct 循环、工具、
技能、沙箱、事件，最终用 Runtime 编排多个 agent 协作。

## 安装

```bash
pip install easy-agent-sdk
```

从源码安装：

```bash
git clone https://github.com/SNHuan/EasyAgent.git
cd EasyAgent
pip install -e ".[dev]"
```

可选依赖：

```bash
pip install easy-agent-sdk[sandbox]
pip install easy-agent-sdk[web]
pip install easy-agent-sdk[all]
```

## 快速开始

```python
import asyncio
from easyagent import LiteLLMModel, ReactAgent


async def main():
    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        system_prompt="你是一个简洁可靠的助手。",
        max_iterations=5,
    )
    result = await agent.run("2 + 2 等于多少？")
    print(result.final_output)


asyncio.run(main())
```

可以创建 `easyagent/config/config.yaml`，也可以直接使用 LiteLLM 支持的环境变量：

```yaml
debug: false

models:
  gpt-4o-mini:
    api_type: openai
    base_url: https://api.openai.com/v1
    api_key: sk-xxx
```

## 分层设计

EasyAgent 围绕三个核心概念展开：

```text
Agent        = 可复用的角色定义
AgentSession = Agent 在 Runtime 中的一次具体运行实例（"分身"）
Runtime      = 多个 AgentSession 共享的执行环境（"世界"）
```

每一层自然建立在上一层之上：

```text
Model
  -> Memory + Context
  -> Agent  (Agent / ReactAgent / SkillAgent / SandboxAgent)
  -> Tool / Skill / Sandbox
  -> Event
  -> Runtime
```

- **Model**：模型适配器和消息结构。
- **Memory + Context**：保存历史，并决定每一轮发给模型的是哪一部分。
- **Agent**：组合 model、memory、context、所需工具/技能/沙箱。内置四个 agent
  类形成继承链：`Agent`（单轮）→ `ReactAgent`（带工具的 ReAct 循环）→
  `SkillAgent` / `SandboxAgent`。循环逻辑就在 agent 自身的 `step()` 方法里，
  不再有单独的 `Loop` 层。
- **Tool / Skill / Sandbox**：模型可调用的函数、按需加载的说明书目录、工具
  执行的环境。
- **Event**：`MessageEvent` 是 agent 之间的结构化通信原语。
- **Runtime**：调度多个 session，并决定何时停止。

完整设计说明见 [docs/architecture.md](docs/architecture.md)。

## Public API

根包暴露常用稳定入口：

```python
from easyagent import (
    Agent, ReactAgent, SkillAgent, SandboxAgent,  # agent 类
    AgentSession, AgentRunResult,                 # 运行实例与结果
    LiteLLMModel, Message,                        # 模型层
    EventBus, MessageEvent,                       # 事件
    ToolManager, SkillManager, register_tool,     # 工具/技能注册
)
```

进阶扩展点放在子包里：

```python
from easyagent.context import FullContext, SlidingWindowContext, SummaryContext
from easyagent.memory import InMemoryMemory
from easyagent.runtime import (
    BaseRuntime, TickBasedRuntime, PipelineRuntime,
    ParallelRuntime, SequentialRuntime, ShuffledRuntime,
    Parallel, Sequential, Shuffled,                  # SchedulePolicy
    DeliverToRecipients, TickDriven,                 # StepPolicy
    StopWhenIdle, StopAfterTicks, StopAfterEvents,   # StopPolicy
    StopWhenMessageMatches, AnyOf,
    SharedStore,
)
from easyagent.events import (
    BaseEvent, WaitEvent,
    LLMCalledEvent, LLMRespondedEvent,
    ToolCalledEvent, ToolResultEvent,
)
```

`ReactAgent` 是带工具 agent 的常规入口。`SkillAgent` 和 `SandboxAgent` 是
预先组合好的 `ReactAgent` 子类，分别封装了「按需加载 SKILL.md」和「沙箱生命周期管理」。

## 学习路径

examples 按层级排序，每个示例只引入一个新概念：

```bash
python examples/00_model_call.py             # 只调模型
python examples/01_single_turn_agent.py      # 最小 Agent
python examples/02_memory_and_context.py     # Memory + Context
python examples/03_react_with_tools.py       # ReactAgent + Tool
python examples/04_skills_lazy_loading.py    # SkillAgent（SKILL.md 包）
python examples/05_sandbox_agent.py          # SandboxAgent（bash/读写文件）
python examples/06_pipeline_runtime.py       # 串行多 agent：PipelineRuntime
python examples/07_event_basics.py           # MessageEvent + EventBus
python examples/08_broadcast_runtime.py      # TickBasedRuntime + DeliverToRecipients
python examples/09_customize_session.py      # 定制 AgentSession 行为
python examples/10_runtime_policies.py       # TickDriven + Shuffled
python examples/11_group_chat.py             # 三人涌现群聊
python examples/12_custom_capability.py      # 自定义工具
```

人机互动版本（人类作为参与者实时加入群聊）：

```bash
python examples/group_chat_demo.py
```

## Tools

```python
from easyagent import LiteLLMModel, ReactAgent, register_tool


@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "获取城市天气。"
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }

    def init(self) -> None: ...

    def execute(self, city: str) -> str:
        return f"{city}天气晴朗。"


agent = ReactAgent(
    model=LiteLLMModel("gpt-4o-mini"),
    tools=[GetWeather],
)
```

`tools=[...]` 直接接受类或实例。Agent 会自动注册一个 `end` 工具，模型调用它
即可主动结束循环。

## Skills

Skill 是按需加载的目录包。`SKILL.md` 是必需入口文件，旁边可以放参考文档、
模板、资源和脚本：

```text
skills/my-skill/
├── SKILL.md
├── references/
├── templates/
├── assets/
└── scripts/
```

```markdown
---
name: my-skill
description: 加载前展示给模型的一句话说明。
allowed-tools:
  - get_weather
---

# 完整说明
```

```python
from easyagent import LiteLLMModel, SkillAgent

agent = SkillAgent(
    model=LiteLLMModel("gpt-4o-mini"),
    skills=["my-skill"],
    skill_root="./skills",
)
```

当模型调用 `load_skill("my-skill")`，skill 的完整正文会被返回，且其声明的
工具会被激活。模型还可以使用以下三个辅助工具按需查看包内资源：

```text
load_skill          # 加载完整说明，激活工具
list_skill_files    # 列出包内文件
read_skill_file     # 读取某个文件
run_skill_script    # 执行 scripts/ 下的脚本
```

## Runtime

任何 `BaseAgent` 只要重写 `AgentSession.on_events`（或 `step`）就可以接入
Runtime。常用调度形态有几个预设：

```python
from easyagent import MessageEvent
from easyagent.runtime import (
    AnyOf, DeliverToRecipients, ShuffledRuntime,
    StopAfterTicks, StopWhenIdle,
)

runtime = ShuffledRuntime(
    agents={"alice": alice, "bob": bob},
    step_policy=DeliverToRecipients(),
    stop_policy=AnyOf([
        StopWhenIdle(grace_steps=1),
        StopAfterTicks(max_ticks=5),
    ]),
)

result = await runtime.run([
    MessageEvent(sender="user", to="*", content="讨论午饭吃什么。")
])
```

如果是固定的串行交接链，使用 `PipelineRuntime`：

```python
from easyagent.runtime import PipelineRuntime

pipeline = PipelineRuntime([researcher, writer, reviewer])
result = await pipeline.run("写一段产品说明。")
```

完整 Runtime / 策略 / 事件的运作流程参见
[docs/runtime_walkthrough.md](docs/runtime_walkthrough.md)。

## 模块结构

```text
easyagent/
├── agent/      # Agent, ReactAgent, SkillAgent, SandboxAgent, AgentSession
├── context/    # FullContext, SlidingWindowContext, SummaryContext
├── events/     # MessageEvent, WaitEvent, EventBus, telemetry events
├── memory/     # InMemoryMemory
├── model/      # LiteLLMModel + Message schema
├── prompt/     # System prompt 构造
├── runtime/    # TickBasedRuntime, PipelineRuntime, 策略, SharedStore
├── sandbox/    # Local / Docker 沙箱
├── skill/      # SKILL.md 加载
├── tool/       # 工具注册与内置工具（bash / file / web / end）
├── config/     # 配置加载
└── debug/      # 日志
```

## 许可证

[MIT License](LICENSE) © 2025 Yiran Peng
