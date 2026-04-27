# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

English | [简体中文](README_CN.md)

EasyAgent is a lightweight agent SDK organised as a small set of composable
layers. The goal is to let you learn agent design step by step: start with a
single model call, then add memory and context, build up to a ReAct loop with
tools and skills, drop into a sandbox, and finally orchestrate multiple agents
through events.

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

Optional extras:

```bash
pip install easy-agent-sdk[sandbox]
pip install easy-agent-sdk[web]
pip install easy-agent-sdk[all]
```

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

EasyAgent is organised around three concrete concepts:

```text
Agent        = reusable definition (a "role")
AgentSession = a running instance of an Agent (a "self" inside a Runtime)
Runtime      = an execution environment shared by multiple sessions
```

The layers build up naturally:

```text
Model
  -> Memory + Context
  -> Agent  (Agent / ReactAgent / SkillAgent / SandboxAgent)
  -> Tool / Skill / Sandbox
  -> Event
  -> Runtime
```

- **Model** — provider adapter and message schema.
- **Memory + Context** — store conversation history and decide what reaches
  the model each turn.
- **Agent** — composes a model, memory, context, and any tools/skills/sandbox
  the agent needs. The four built-in classes form an inheritance chain:
  `Agent` (single-turn) → `ReactAgent` (ReAct loop with tools) → `SkillAgent`
  / `SandboxAgent`. The loop is part of the agent's own `step()` method —
  there is no separate `Loop` layer.
- **Tool / Skill / Sandbox** — callable functions the model can use, loadable
  instruction packages, and the execution environment for sandboxed tools.
- **Event** — `MessageEvent` is the structured communication primitive
  between agents.
- **Runtime** — schedules multiple sessions and decides when to stop.

See [docs/architecture.md](docs/architecture.md) for the full design guide.

## Public API

The root package exposes the common SDK surface:

```python
from easyagent import (
    Agent, ReactAgent, SkillAgent, SandboxAgent,  # agent classes
    AgentSession, AgentRunResult,                 # session & result
    LiteLLMModel, Message,                        # model layer
    EventBus, MessageEvent,                       # events
    ToolManager, SkillManager, register_tool,     # tool / skill registries
)
```

Submodules expose advanced building blocks:

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

`ReactAgent` is the typical entry point for tool-using agents. `SkillAgent`
and `SandboxAgent` are pre-configured `ReactAgent` subclasses that add skill
loading and sandbox lifecycle management respectively.

## Learning Path

The examples are ordered by layer. Each one introduces one new idea:

```bash
python examples/00_model_call.py             # Just call the model
python examples/01_single_turn_agent.py      # Compose a minimal Agent
python examples/02_memory_and_context.py     # Memory + Context
python examples/03_react_with_tools.py       # ReactAgent + Tool
python examples/04_skills_lazy_loading.py    # SkillAgent (SKILL.md packages)
python examples/05_sandbox_agent.py          # SandboxAgent (bash, write/read file)
python examples/06_pipeline_runtime.py       # Linear multi-agent: PipelineRuntime
python examples/07_event_basics.py           # MessageEvent + EventBus
python examples/08_broadcast_runtime.py      # TickBasedRuntime + DeliverToRecipients
python examples/09_customize_session.py      # Customize AgentSession behaviour
python examples/10_runtime_policies.py       # TickDriven + Shuffled
python examples/11_group_chat.py             # Three-agent emergent group chat
python examples/12_custom_capability.py      # Custom tool
```

A richer interactive demo (human-in-the-loop group chat) is also available:

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

```markdown
---
name: my-skill
description: One-line summary shown before loading.
allowed-tools:
  - get_weather
---

# Full instructions
```

```python
from easyagent import LiteLLMModel, SkillAgent

agent = SkillAgent(
    model=LiteLLMModel("gpt-4o-mini"),
    skills=["my-skill"],
    skill_root="./skills",
)
```

When the model calls `load_skill("my-skill")`, the skill's full body is
returned and its declared tools are activated. Three additional helper tools
let the model navigate the package as needed:

```text
load_skill          # load full instructions, activate tools
list_skill_files    # list packaged files
read_skill_file     # read one file
run_skill_script    # execute a script under scripts/
```

## Runtime

Any `BaseAgent` joins a runtime by overriding `AgentSession.on_events` (or
`step`). A few presets cover the common scheduling shapes:

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
    MessageEvent(sender="user", to="*", content="Discuss lunch options.")
])
```

For a fixed linear hand-off chain, use `PipelineRuntime`:

```python
from easyagent.runtime import PipelineRuntime

pipeline = PipelineRuntime([researcher, writer, reviewer])
result = await pipeline.run("Write a one-paragraph product blurb.")
```

See [docs/runtime_walkthrough.md](docs/runtime_walkthrough.md) for a full
walkthrough of how the runtime, policies, and events interact.

## Module Layout

```text
easyagent/
├── agent/      # Agent, ReactAgent, SkillAgent, SandboxAgent, AgentSession
├── context/    # FullContext, SlidingWindowContext, SummaryContext
├── events/     # MessageEvent, WaitEvent, EventBus, telemetry events
├── memory/     # InMemoryMemory
├── model/      # LiteLLMModel + Message schema
├── prompt/     # System-prompt builders
├── runtime/    # TickBasedRuntime, PipelineRuntime, policies, SharedStore
├── sandbox/    # Local / Docker sandboxes
├── skill/      # SKILL.md loading
├── tool/       # Tool registry + built-ins (bash, file, web, end)
├── config/     # Config loading
└── debug/      # Logging
```

## License

[MIT License](LICENSE) © 2025 Yiran Peng
