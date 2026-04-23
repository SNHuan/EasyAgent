# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

English | [简体中文](README_CN.md)

EasyAgent is a lightweight agent system built around a small set of core abstractions:

- `BaseLLM` for model access
- `BaseLoop` for execution strategy
- `BaseMemory` for full conversation history
- `BaseContext` for model-facing context assembly
- `BaseCapability` for optional features such as tools, skills, and sandbox resources

The project is intentionally incremental: each layer is usable on its own, and higher-level features are built directly on top of lower-level ones.

## Current Architecture

```text
LLM -> Loop -> Memory / Context -> Capability -> Agent
```

Core ideas:

- `Agent` is a thin orchestrator
- `AgentSession` owns run-time state
- `Memory` stores full history
- `Context` decides what the model sees
- `Capability` adds optional behavior without creating more agent subclasses

## Features

- Multi-model support through LiteLLM
- ReAct and single-turn loop abstractions
- Memory / context split
- Tool calling via `ToolManager`
- Skills with progressive disclosure
- Sandbox support through capability composition
- Local and Docker sandbox implementations

## Installation

```bash
pip install easy-agent-sdk
```

Optional extras:

```bash
pip install easy-agent-sdk[sandbox]
pip install easy-agent-sdk[web]
pip install easy-agent-sdk[all]
```

From source:

```bash
git clone https://github.com/SNHuan/EasyAgent.git
cd EasyAgent
pip install -e ".[dev]"
```

## Configuration

Create a config file such as `config.yaml`:

```yaml
debug: true

models:
  gpt-4o-mini:
    api_type: openai
    base_url: https://api.openai.com/v1
    api_key: sk-xxx
    kwargs:
      temperature: 0.7
      max_tokens: 4096
```

Then point `EA_DEFAULT_CONFIG` to it:

```bash
export EA_DEFAULT_CONFIG=/path/to/config.yaml
```

## Quick Start

Minimal `ReactAgent`:

```python
import asyncio

from easyagent import InMemoryMemory, LiteLLMModel, ReactAgent, SlidingWindowContext


async def main() -> None:
    model = LiteLLMModel(model="gpt-4o-mini")
    agent = ReactAgent(
        model=model,
        system_prompt="You are a concise assistant.",
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=12),
        max_iterations=5,
    )

    result = await agent.run("Introduce EasyAgent in one sentence.")
    print(result)


asyncio.run(main())
```

There is also a runnable example:

```bash
python examples/simple_react_agent.py
```

## Tools

Define a tool with `@register_tool`:

```python
from easyagent.tool import register_tool


@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "Get weather for a city."
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
        },
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str, **kwargs) -> str:
        return f"The weather in {city} is sunny."
```

Use it with `ReactAgent`:

```python
agent = ReactAgent(
    model=LiteLLMModel(model="gpt-4o-mini"),
    tools=["get_weather"],
)
```

## Skills

Skills are markdown-based capability packages loaded on demand.

Directory layout:

```text
./skills/
  my-skill/
    SKILL.md
```

Example `SKILL.md`:

```markdown
---
name: my-skill
description: One-line summary shown before loading.
allowed-tools:
  - get_weather
---

# Full instructions
```

Usage:

```python
agent = ReactAgent(
    model=LiteLLMModel(model="gpt-4o-mini"),
    skills=["my-skill"],
    skill_dir="./skills",
)
```

The model only sees the skill summary at first. When it decides to load the skill, `SkillCapability` returns the full body and activates the declared tools for the current session.

## Sandbox

`SandboxAgent` is now a thin preset built from:

- `SandboxCapability`
- `ToolCapability`
- `ReActLoop`

Example:

```python
import asyncio

from easyagent import LiteLLMModel, SandboxAgent
from easyagent.sandbox import LocalSandbox


async def main() -> None:
    model = LiteLLMModel(model="gpt-4o-mini")
    agent = SandboxAgent(
        model=model,
        sandbox=LocalSandbox(),
    )
    result = await agent.run("Run a short Python command and tell me the output.")
    print(result)


asyncio.run(main())
```

Built-in sandbox tools:

- `bash`
- `write_file`
- `read_file`

## Main Modules

```text
easyagent/
├── agent/       # Agent, ReactAgent, SandboxAgent, AgentSession
├── capability/  # BaseCapability, Tool/Skill/Sandbox capabilities
├── context/     # FullContext, SlidingWindowContext, SummaryContext
├── loop/        # BaseLoop, ReActLoop, SingleTurnLoop
├── memory/      # BaseMemory, InMemoryMemory
├── model/       # BaseLLM, LiteLLMModel, Message, ToolCall
├── sandbox/     # BaseSandbox, DockerSandbox, LocalSandbox
├── skill/       # Skill, SkillManager, SKILL.md loader
├── tool/        # Tool protocol, ToolManager, built-in tools
├── prompt/      # Prompt templates
├── config/      # Config loading
└── debug/       # Logging helpers
```

## Status

The current codebase has already been migrated to the new architecture:

- session-owned runtime state
- memory/context split
- capability-based feature composition

MCP integration and broader documentation cleanup are still future work.

## License

[MIT License](LICENSE) © 2025 Yiran Peng
