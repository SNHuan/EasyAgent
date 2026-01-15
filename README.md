# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

English | [简体中文](README_CN.md)

A lightweight AI Agent framework built on LiteLLM, featuring multi-model support, tool calling, sandbox execution, and intelligent memory management.

> **~1200 lines of code, production-ready Agent capabilities** — Multi-model adapters, tool calling, sandbox isolation, smart memory, ReAct reasoning, DAG pipelines, debug tracing.

## Features

- **Multi-Model Support** - Unified interface via LiteLLM for OpenAI, Anthropic, Gemini, and more
- **Tool Calling** - Protocol-based tool definition with `@register_tool` decorator
- **Sandbox Execution** - Isolated code execution in Docker or local environment
- **Memory** - Sliding window + auto-summarization strategies for context management
- **ReAct Loop** - Standard think → act → observe reasoning cycle
- **DAG Pipeline** - Directed Acyclic Graph workflow orchestration with parallel execution
- **Debug Friendly** - Colored logging, token usage and cost tracking

## Installation

```bash
pip install easy-agent-sdk
```

**With optional dependencies:**

```bash
# Docker sandbox support
pip install easy-agent-sdk[sandbox]

# Web tools (SerperSearch)
pip install easy-agent-sdk[web]

# All optional dependencies
pip install easy-agent-sdk[all]
```

**From source:**

```bash
git clone https://github.com/SNHuan/EasyAgent.git
cd EasyAgent
pip install -e ".[dev]"
```

## Quick Start

### 1. Configuration

Create a config file `config.yaml`:

```yaml
debug: true
summary_model: gpt-4o-mini

models:
  gpt-4o-mini:
    api_type: openai
    base_url: https://api.openai.com/v1
    api_key: sk-xxx
    kwargs:
      max_tokens: 4096
      temperature: 0.7
```

Set environment variable:

```bash
export EA_DEFAULT_CONFIG=/path/to/config.yaml
```

### 2. Define Tools

```python
from easyagent.tool import register_tool

@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "Get the weather for a city."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str) -> str:
        return f"The weather in {city} is sunny, 25°C."
```

### 3. Create Agent

```python
import asyncio
from easyagent import ReactAgent
from easyagent.config import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel

config = ModelConfig.load()
model = LiteLLMModel(**config.get_model("gpt-4o-mini"))

agent = ReactAgent(
    model=model,
    tools=["get_weather"],
    system_prompt="You are a helpful assistant.",
    max_iterations=10,
)

result = asyncio.run(agent.run("What's the weather in Beijing?"))
print(result)
```

### 4. SandboxAgent (Code Execution)

```python
import asyncio
from easyagent import SandboxAgent
from easyagent.config import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel

config = ModelConfig.load()
model = LiteLLMModel(**config.get_model("gpt-4o"))

# Local sandbox (for development)
agent = SandboxAgent(model=model)

# Docker sandbox (for production)
agent = SandboxAgent(
    model=model,
    sandbox_type="docker",
    image="python:3.12-slim",
    cpu_limit=2.0,
    memory_limit="1g",
    network=True,
)

result = asyncio.run(agent.run("Write a fibonacci program and run it"))
print(result)
```

**SandboxAgent** comes with built-in tools:
- `bash` - Execute shell commands
- `write_file` - Write files (handles complex content safely)
- `read_file` - Read files

## Core Components

### Agent

| Class | Description |
|-------|-------------|
| `ReactAgent` | ReAct loop: think → act → observe |
| `ToolAgent` | Tool registration and execution |
| `SandboxAgent` | ReactAgent with isolated code execution |

### Sandbox

```python
from easyagent import DockerSandbox, LocalSandbox, create_sandbox

# Factory function
sandbox = create_sandbox("docker", image="python:3.12-slim")

# Or direct instantiation
sandbox = DockerSandbox(
    image="python:3.12-slim",
    memory_limit="512m",
    cpu_limit=1.0,
    network=True,
)

async with sandbox:
    result = await sandbox.exec_command("python --version")
    print(result.output)
    
    await sandbox.write_file("hello.py", "print('Hello!')")
    result = await sandbox.exec_command("python hello.py")
```

### Memory

```python
from easyagent.memory import SlidingWindowMemory, SummaryMemory

# Sliding window
memory = SlidingWindowMemory(max_messages=20, max_tokens=4000)

# Auto-summary for long tasks
memory = SummaryMemory(task_id="task_001", reserve_ratio=0.3)
```

### Pipeline

DAG-based workflow with parallel execution:

```python
import asyncio
from easyagent.pipeline.base import BaseNode, BasePipeline, NodeContext

class FetchData(BaseNode):
    async def execute(self, ctx: NodeContext) -> None:
        ctx.data = "raw_data"

class ProcessA(BaseNode):
    async def execute(self, ctx: NodeContext) -> None:
        ctx.result_a = f"{ctx.data}_A"

class ProcessB(BaseNode):
    async def execute(self, ctx: NodeContext) -> None:
        ctx.result_b = f"{ctx.data}_B"

fetch = FetchData()
process_a = ProcessA()
process_b = ProcessB()

fetch >> [process_a, process_b]  # Parallel branches

pipeline = BasePipeline(root=fetch)
ctx = asyncio.run(pipeline.run())
```

### Built-in Tools

| Tool | Description | Required |
|------|-------------|----------|
| `bash` | Execute shell commands in sandbox | SandboxAgent |
| `write_file` | Write files to sandbox | SandboxAgent |
| `read_file` | Read files from sandbox | SandboxAgent |
| `serper_search` | Google search via Serper API | `SERPER_API_KEY` env |

## Project Structure

```
easyagent/
├── agent/          # ReactAgent, ToolAgent, SandboxAgent
├── model/          # LiteLLMModel, Message, ToolCall
├── memory/         # SlidingWindowMemory, SummaryMemory
├── tool/           # ToolManager, @register_tool
│   ├── code/       # bash, write_file, read_file
│   └── web/        # serper_search
├── sandbox/        # DockerSandbox, LocalSandbox
├── pipeline/       # BaseNode, BasePipeline
├── config/         # ModelConfig, AppConfig
├── prompt/         # Prompt templates
└── debug/          # Logger, LogCollector
```

## License

[MIT License](LICENSE) © 2025 Yiran Peng
