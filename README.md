# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

English | [简体中文](README_CN.md)

A lightweight AI Agent framework built on LiteLLM, featuring multi-model support, tool calling, and intelligent memory management.

> **~809 lines of code, production-ready Agent capabilities** — Multi-model adapters, tool calling, smart memory, ReAct reasoning, DAG pipelines, debug tracing.

## Features

- **Multi-Model Support** - Unified interface via LiteLLM for OpenAI, Anthropic, Gemini, and more
- **Tool Calling** - Protocol-based tool definition with `@register_tool` decorator
- **Memory** - Sliding window + auto-summarization strategies for context management
- **ReAct Loop** - Standard think → act → observe reasoning cycle
- **DAG Pipeline** - Directed Acyclic Graph workflow orchestration with parallel execution
- **Debug Friendly** - Colored logging, token usage and cost tracking

## Installation

```bash
pip install easy-agent-sdk
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
from easyagent.agent import ReactAgent
from easyagent.config.base import ModelConfig
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

## Core Components

### Agent

| Class | Description |
|-------|-------------|
| `ReactAgent` | ReAct loop: think → act → observe |
| `ToolAgent` | Tool registration and execution |

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

### Debug

```python
from easyagent.debug.log import LogCollector, Logger

log = Logger("MyApp")

with LogCollector() as collector:
    log.info("Step 1")
    log.info("Step 2")

print(collector.to_text())
```

## Project Structure

```
easyagent/
├── agent/          # ReactAgent, ToolAgent
├── model/          # LiteLLMModel, Message, ToolCall
├── memory/         # SlidingWindowMemory, SummaryMemory
├── tool/           # ToolManager, @register_tool
├── pipeline/       # BaseNode, BasePipeline
├── config/         # ModelConfig
├── prompt/         # Prompt templates
└── debug/          # Logger, LogCollector
```

## License

[MIT License](LICENSE) © 2025 Yiran Peng
