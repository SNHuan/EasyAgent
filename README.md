# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

English | [简体中文](README_CN.md)

EasyAgent is a lightweight agent SDK organised as a small set of composable
layers. The goal is to let you learn agent design step by step: start with a
single model call, then add memory and context, build up to a ReAct loop with
tools and skills, drop into a sandbox, and finally orchestrate multiple agents
through the Entity-World-Schedule architecture.

## Install

```bash
pip install easy-agent-sdk
```

From source:

```bash
git clone https://github.com/SNHuan/EasyAgent.git
cd EasyAgent
pip install -e ".[dev]"
```

The default install includes model adapters, sandbox helpers, web helpers, and
MCP integration.

## Quick Start

```python
import asyncio
from easyagent import LiteLLMModel, ReactAgent


async def main():
    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        system_prompt="You are a concise assistant.",
        max_iterations=5,
    )
    result = await agent.run("What is 2 + 2?")
    print(result.final_output)


asyncio.run(main())
```

Create `easyagent/config/config.yaml` or configure LiteLLM through environment
variables:

```yaml
debug: false

models:
  gpt-4o-mini:
    api_type: openai
    base_url: https://api.openai.com/v1
    api_key: sk-xxx
```

## Layered Design

EasyAgent is organised around three layers:

```text
Single-agent:    Model + Memory + Context + Tool → Agent / ReactAgent / SkillAgent / SandboxAgent
Multi-agent:     Entity + World + Schedule → Runtime
Presets:         sequential / fanout / debate / chatroom / groupchat
```

- **Model** — provider adapter and message schema.
- **Memory + Context** — store conversation history and decide what reaches
  the model each turn.
- **Agent** — composes a model, memory, context, and any tools/skills/sandbox.
  Four built-in classes: `Agent` (single-turn) → `ReactAgent` (ReAct loop) →
  `SkillAgent` / `SandboxAgent`.
- **Entity** — wraps an Agent (or any async actor) for multi-agent participation.
  Protocol: `id` property + `async act(Perception) -> Action | None`.
- **World** — the environment entities perceive and act upon.
  Built-ins: `ConversationWorld`, `PipelineWorld`, `SpatialWorld`, `StatefulWorld`.
- **Schedule** — determines who acts next.
  Built-ins: `TakeTurns`, `RoundRobin`, `AllParallel`, `Reactive`, `MaxTicks`, `UntilIdle`.
- **Runtime** — the perceive-act-apply loop wiring Entity + World + Schedule.

See [docs/architecture.md](docs/architecture.md) for the full design guide.

## Public API

The root package exposes the common SDK surface:

```python
from easyagent import (
    # single-agent
    Agent, ReactAgent, SkillAgent, SandboxAgent,
    AgentSession, AgentRunResult,
    LiteLLMModel, Message,
    EventBus, MessageEvent,
    ToolManager, SkillManager, register_tool,
    MCPToolset, load_mcp_tools, register_mcp_tools,
    # multi-agent protocols
    Entity, World, Schedule, Runtime, RuntimeResult,
    # perception & action types
    Perception, Speak, Silent, ChatMessage,
    # entities
    LLMEntity, TeamEntity, HumanEntity,
    # worlds
    ConversationWorld, PipelineWorld, SpatialWorld, StatefulWorld, SharedState,
    # schedules
    TakeTurns, RoundRobin, AllParallel, MaxTicks, UntilIdle, Reactive,
    # presets
    sequential, fanout, debate, chatroom, groupchat,
)
```

## Learning Path

The examples are ordered by layer. Each one introduces one new idea:

```bash
# Single agent (00–06)
python examples/00_model_call.py             # Just call the model
python examples/01_single_turn_agent.py      # Compose a minimal Agent
python examples/02_memory_and_context.py     # Memory + Context
python examples/03_react_with_tools.py       # ReactAgent + tool calls
python examples/04_skills_lazy_loading.py    # SkillAgent (SKILL.md packages)
python examples/05_sandbox_agent.py          # SandboxAgent (bash, write/read file)
python examples/06_custom_tool.py            # Define your own tool

# Multi-agent: Entity-World-Schedule (07–14)
python examples/07_two_agents_talk.py        # LLMEntity + ConversationWorld + RoundRobin
python examples/08_sequential.py             # sequential() preset
python examples/09_chatroom.py               # Manual turn-taking + if/else
python examples/10_groupchat.py              # Reactive schedule, LLM picks next
python examples/11_debate_and_judge.py       # Third-party judge after debate
python examples/12_nested.py                 # TeamEntity: Runtime-as-Entity nesting
python examples/13_shared_state.py           # SharedState + StatefulWorld blackboard
python examples/14_advanced_runtime.py       # SpatialWorld: 2D grid + range-limited perception

# MCP examples (external tool sources)
python examples/mcp/fastmcp_in_memory.py     # Wrap a FastMCP server as EasyAgent tools
python examples/mcp/config_load.py           # Load tools from mcp_config.example.json
```

## Tools

```python
from easyagent import LiteLLMModel, ReactAgent, register_tool


@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "Get weather for a city."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }

    def init(self) -> None: ...

    def execute(self, city: str) -> str:
        return f"Sunny in {city}."


agent = ReactAgent(
    model=LiteLLMModel("gpt-4o-mini"),
    tools=[GetWeather],
)
```

Pass tool classes or instances directly via `tools=[...]`. The agent
automatically registers an `end` tool — call it to terminate the loop early.

## MCP Tools

EasyAgent can consume MCP servers as external tool sources. MCP support is
included in the default install.

Use a standard FastMCP/MCP config. The `mcpServers` keys act as natural tool
categories:

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

Register discovered MCP tools into a `ToolManager`, then decide per session
which tools are visible to the model:

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

You can also filter FastMCP tools by tags:

```python
await register_mcp_tools(tool_manager, mcp_config, tags=["demo"])
```

See `examples/mcp/` for runnable examples.

## Skills

Skills are directory packages loaded on demand. `SKILL.md` is the required
entry file; supporting files can live alongside it:

```text
skills/my-skill/
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
    skill_root="./skills",
)
```

## Multi-agent

Wrap any `Agent` as an `LLMEntity`, then compose with presets:

```python
from easyagent import LiteLLMModel, ReactAgent, LLMEntity, sequential

model = LiteLLMModel("gpt-4o-mini")
researcher = LLMEntity("researcher", ReactAgent(model=model, name="researcher", system_prompt="..."))
writer     = LLMEntity("writer",     ReactAgent(model=model, name="writer",     system_prompt="..."))
reviewer   = LLMEntity("reviewer",   ReactAgent(model=model, name="reviewer",   system_prompt="..."))

result = await sequential([researcher, writer, reviewer], "Write a product blurb.")
print(result.last_speech)
```

Available presets: `sequential` / `fanout` / `chatroom` / `groupchat` /
`debate`. For recursive nesting, wrap an inner `Runtime` as a `TeamEntity`
and drop it into any outer pipeline. See `examples/07_*` through
`examples/14_*` for walkthroughs.

### Custom World

The architecture is extensible beyond conversation. Swap the World to get
entirely different behaviour with the same Entity and Schedule:

```python
from easyagent import SpatialWorld, Grid2D, Runtime, RoundRobin, MaxTicks

grid = Grid2D()
grid.place("alice", (0, 0))
grid.place("bob", (5, 5))

world = SpatialWorld(grid=grid, listen_radius=3.0)
schedule = MaxTicks(inner=RoundRobin(ids=["alice", "bob"]), n=10)

rt = Runtime(world=world, entities={"alice": alice, "bob": bob}, schedule=schedule)
result = await rt.run("Start exploring")
```

## Module Layout

```text
easyagent/
├── agent/      # Agent, ReactAgent, SkillAgent, SandboxAgent, AgentSession
├── core/       # Entity, World, Schedule protocols + Runtime loop
├── entities/   # LLMEntity, TeamEntity, HumanEntity
├── worlds/     # ConversationWorld, PipelineWorld, SpatialWorld, StatefulWorld
├── presets.py  # sequential, fanout, debate, chatroom, groupchat
├── context/    # SlidingWindowContext, SummaryContext, MultiAgentFormatter
├── events/     # MessageEvent, EventBus, telemetry events
├── memory/     # InMemoryMemory
├── model/      # LiteLLMModel + Message schema
├── prompt/     # System-prompt builders
├── sandbox/    # Local / Docker sandboxes
├── skill/      # SKILL.md loading
├── tool/       # Tool registry + built-ins (bash, file, web, end)
├── config/     # Config loading
└── debug/      # Logging
```

## License

[MIT License](LICENSE) © 2025 Yiran Peng
