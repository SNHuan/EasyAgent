# EasyAgent

![EasyAgent banner](assert/easyagent_banner.png)

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

[English](README.md) | 中文

EasyAgent 是一个轻量级 Agent SDK，核心设计是分层组合。项目希望让你能逐步学习
Agent 的设计：从最直接的模型调用开始，依次加入记忆、上下文、ReAct 循环、工具、
技能、沙箱，最终通过 Entity-World-Schedule 架构编排多 agent 协作。

你会得到：

- 一套小而清晰的单 agent 栈：model、memory、context、tools、skills、sandbox。
- 用于多 agent 系统的 Runtime 原语：Entity、World、Schedule、Runtime。
- 兼容 Agent Skills 的技能加载：可从 `.easyagent/skills`、`.claude/skills`、
  `.codex/skills` 或自定义目录加载。
- 需要可观测性时，可接入 tracing、store 和本地 dashboard。

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

默认安装已经包含模型适配、沙箱辅助、Web 辅助和 MCP 接入。

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

## 配置

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

EasyAgent 围绕三层展开：

```text
单 agent：    Model + Memory + Context + Tool → Agent / ReactAgent / SkillAgent / SandboxAgent
多 agent：    Entity + World + Schedule → Runtime
预设：       sequential / fanout / debate / chatroom / groupchat
```

- **Model**：模型适配器和消息结构。
- **Memory + Context**：保存历史，并决定每一轮发给模型的是哪一部分。
- **Agent**：组合 model、memory、context、所需工具/技能/沙箱。内置四个 agent
  类：`Agent`（单轮）→ `ReactAgent`（ReAct 循环）→ `SkillAgent` / `SandboxAgent`。
- **Entity**：把 Agent（或任意异步参与者）包装成多 agent 参与者。
  协议：`id` 属性 + `async act(Perception) -> Action | None`。
- **World**：Entity 感知和作用的环境。
  内置：`ConversationWorld`、`PipelineWorld`、`SpatialWorld`、`StatefulWorld`。
- **Schedule**：决定谁下一个行动。
  内置：`TakeTurns`、`RoundRobin`、`AllParallel`、`Reactive`、`MaxTicks`、`UntilIdle`。
- **Runtime**：串联 Entity + World + Schedule 的 perceive-act-apply 循环。

完整设计说明见 [docs/architecture.md](docs/architecture.md)。

## 学习路径

examples 按层级排序，每个示例只引入一个新概念：

```bash
# 单 agent（00–06）
python examples/00_model_call.py             # 只调模型
python examples/01_single_turn_agent.py      # 最小 Agent
python examples/02_memory_and_context.py     # Memory + Context
python examples/03_react_with_tools.py       # ReactAgent + 工具调用
python examples/04_skills_lazy_loading.py    # SkillAgent（SKILL.md 包）
python examples/05_sandbox_agent.py          # SandboxAgent（bash / 读写文件）
python examples/06_custom_tool.py            # 自定义工具

# 多 agent：Entity-World-Schedule（07–14）
python examples/07_two_agents_talk.py        # LLMEntity + ConversationWorld + RoundRobin
python examples/08_sequential.py             # sequential() 预设
python examples/09_chatroom.py               # 手动轮次 + if/else 路由
python examples/10_groupchat.py              # Reactive 调度，LLM 选下一个
python examples/11_debate_and_judge.py       # 辩论 + 第三方仲裁
python examples/12_nested.py                 # TeamEntity：Runtime 当 Entity 嵌套
python examples/13_shared_state.py           # SharedState + StatefulWorld 黑板协作
python examples/14_advanced_runtime.py       # SpatialWorld：2D 网格 + 距离感知

# MCP 示例（外部工具来源）
python examples/mcp/fastmcp_in_memory.py     # 把 FastMCP server 包成 EasyAgent 工具
python examples/mcp/config_load.py           # 从 mcp_config.example.json 加载工具
```

## 工具

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

`tools=[...]` 直接接受类或实例。ReAct 循环会在模型返回工具调用时继续执行；
当模型返回无工具调用的普通 assistant 文本时，将其视为最终答案。

## MCP 工具

EasyAgent 可以把 MCP server 当成外部工具来源接入。MCP 支持已经包含在默认安装中。

配置使用标准 FastMCP/MCP 形态。`mcpServers` 的 key 天然就是工具分类：

```json
{
  "mcpServers": {
    "literature": {
      "command": "python",
      "args": ["./examples/mcp/servers/literature_server.py"]
    }
  }
}
```

把发现到的 MCP 工具注册进 `ToolManager`，再由每个 session 决定本轮暴露给模型的工具：

```python
from easyagent import LiteLLMModel, ReactAgent, ToolManager, register_mcp_tools

tool_manager = ToolManager(discover_builtin=False)
literature_tools = await register_mcp_tools(
    tool_manager,
    mcp_config,
    servers=["literature"],
)

agent = ReactAgent(model=LiteLLMModel("gpt-4o-mini"), tool_manager=tool_manager)
session = agent.create_session()
session.enabled_tools.extend(literature_tools)
```

也可以按 FastMCP tool tags 过滤：

```python
await register_mcp_tools(tool_manager, mcp_config, tags=["demo"])
```

可运行示例见 `examples/mcp/`。

## 技能

Skill 兼容 [Agent Skills](https://agentskills.io/) 标准，按需加载。
`SKILL.md` 是必需入口文件，必须包含 YAML frontmatter，至少有 `name` 和
`description`，并且 `name` 必须和父目录名一致。

```text
.easyagent/skills/my-skill/
├── SKILL.md
├── references/
├── templates/
├── assets/
└── scripts/
```

```python
from easyagent import LiteLLMModel, SkillAgent

agent = SkillAgent(
    model=LiteLLMModel("gpt-4o-mini"),
    skills=["my-skill"],
)
```

默认从 `.easyagent/skills` 发现技能。可以设置 `EA_SKILLS_DIR` 加载其他
Agent Skills 兼容目录，例如 `.claude/skills` 或 `.codex/skills`。多个目录
使用系统路径分隔符连接（macOS/Linux 为 `:`，Windows 为 `;`）。

## 多 agent

把任意 `Agent` 包成 `LLMEntity`，然后用 preset 组合：

```python
from easyagent import LiteLLMModel, ReactAgent, LLMEntity, sequential

model = LiteLLMModel("gpt-4o-mini")
researcher = LLMEntity("researcher", ReactAgent(model=model, name="researcher", system_prompt="..."))
writer     = LLMEntity("writer",     ReactAgent(model=model, name="writer",     system_prompt="..."))
reviewer   = LLMEntity("reviewer",   ReactAgent(model=model, name="reviewer",   system_prompt="..."))

result = await sequential([researcher, writer, reviewer], "写一段产品介绍。")
print(result.last_speech)
```

可用预设：`sequential` / `fanout` / `chatroom` / `groupchat` / `debate`。
用 `TeamEntity` 把内层 `Runtime` 包装成单个 Entity，就能递归嵌套。
每个形态的最小例子见 `examples/07_*` 到 `examples/14_*`。

### 自定义 World

架构的扩展性不局限于对话。换一个 World 就能得到完全不同的行为：

```python
from easyagent import SpatialWorld, Grid2D, Runtime, RoundRobin, MaxTicks

grid = Grid2D()
grid.place("alice", (0, 0))
grid.place("bob", (5, 5))

world = SpatialWorld(grid=grid, listen_radius=3.0)
schedule = MaxTicks(inner=RoundRobin(ids=["alice", "bob"]), n=10)

rt = Runtime(world=world, entities={"alice": alice, "bob": bob}, schedule=schedule)
result = await rt.run("开始探索")
```

## 可观测性

EasyAgent 可以把 agent session 和 runtime trace 持久化到 SQLite，并通过
本地 dashboard 查看日志、事件、消息历史和 token 统计：

```bash
easyagent dashboard
```

默认读取 `.easyagent/traces.db`。也可以指定 trace store，并自动打开浏览器：

```bash
easyagent dashboard --db path/to/traces.db --open
```

dashboard 同时理解独立 agent session 和 runtime trace。只要应用把 runtime
事件写入选定 trace store，runtime/world/entity/session 树就会自动展示出来。

自定义事件可以通过 `DisplayHint` 指定前端展示位置。比如下面这个事件会
以 `PlannerStepEvent` 持久化，并在 Messages tab 中显示成 assistant 气泡：

```python
from easyagent import CustomTraceEvent, DisplayHint, EventBus, MemoryStore, TraceRecorder

store = MemoryStore()
bus = EventBus()
TraceRecorder(store).attach(bus)

await bus.publish(
    CustomTraceEvent(
        event_type="PlannerStepEvent",
        session_id="sess_planner",
        agent_id="planner",
        summary="Planner selected search_docs",
        payload={"step": "search_docs"},
        display=DisplayHint.messages(
            "Need to inspect README and pyproject first.",
            role="assistant",
            title="Planner step",
            source="planner",
        ),
    )
)
```

## 公共 API

根包暴露常用稳定入口：

```python
from easyagent import (
    # 单 agent
    Agent, ReactAgent, SkillAgent, SandboxAgent,
    AgentSession, AgentRunResult,
    LiteLLMModel, Message,
    EventBus, MessageEvent,
    ToolManager, SkillManager, register_tool,
    MCPToolset, load_mcp_tools, register_mcp_tools,
    # 多 agent 协议
    Entity, World, Schedule, Runtime, RuntimeResult,
    # 感知与动作类型
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

## 模块结构

```text
easyagent/
├── agent/      # Agent, ReactAgent, SkillAgent, SandboxAgent, AgentSession
├── core/       # Entity, World, Schedule 协议 + Runtime 循环
├── entities/   # LLMEntity, TeamEntity, HumanEntity
├── worlds/     # ConversationWorld, PipelineWorld, SpatialWorld, StatefulWorld
├── presets.py  # sequential, fanout, debate, chatroom, groupchat
├── context/    # SlidingWindowContext, SummaryContext, MultiAgentFormatter
├── events/     # MessageEvent, EventBus, 遥测事件
├── memory/     # InMemoryMemory
├── model/      # LiteLLMModel + Message schema
├── prompt/     # System prompt 构造
├── sandbox/    # Local / Docker 沙箱
├── skill/      # SKILL.md 加载
├── tool/       # 工具注册与内置工具（bash / file / web / skill helpers）
├── config/     # 配置加载
└── debug/      # 日志
```

## 许可证

[MIT License](LICENSE) © 2025 Yiran Peng
