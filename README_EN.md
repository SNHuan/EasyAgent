# EasyAgent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

English | [中文](README.md)

A lightweight AI Agent framework built on LiteLLM, featuring multi-model support, tool calling, and intelligent memory management.

## Features

- 🔌 **Multi-Model Support** - Unified interface via LiteLLM for OpenAI, Anthropic, Gemini, and more
- 🛠️ **Tool Calling** - Protocol-based tool definition with `@register_tool` decorator
- 🧠 **Smart Memory** - Sliding window + auto-summarization strategies for context management
- 🔄 **ReAct Loop** - Standard think → act → observe reasoning cycle
- 🔀 **DAG Pipeline** - Directed Acyclic Graph workflow orchestration with parallel execution
- 📊 **Debug Friendly** - Colored logging, token usage and cost tracking

## Installation

**Development mode (recommended):**

```bash
git clone https://github.com/pyr-sh/terminal-bench.git
cd terminal-bench
pip install -e .
```

**Install dev dependencies:**

```bash
pip install -e ".[dev]"
```

**Core dependencies:**
- `litellm>=1.80.0`
- `pydantic>=2.12.5`

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                         User Layer                           │
│                      (Input / Output)                        │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                        Agent Layer                           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  ReactAgent  (ReAct Loop: think -> act -> observe)     │  │
│  │      ↓ extends                                         │  │
│  │  ToolAgent   (Tool Registration & Execution)           │  │
│  │      ↓ extends                                         │  │
│  │  BaseAgent   (Model + Memory + History Management)     │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────┬──────────────────┬──────────────────┬────────────┘
            │                  │                  │
            ▼                  ▼                  ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│      Model       │  │      Memory      │  │       Tool       │
│                  │  │                  │  │                  │
│  BaseLLM         │  │  BaseMemory      │  │  Tool Protocol   │
│      ↓           │  │      ↓           │  │      ↓           │
│  LiteLLMModel    │  │  SlidingWindow   │  │  ToolManager     │
│  (OpenAI/Claude) │  │  SummaryMemory   │  │  @register_tool  │
└────────┬─────────┘  └──────────────────┘  └──────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│                       Schema Layer                           │
│          Message  |  ToolCall  |  LLMResponse                │
└──────────────────────────────────────────────────────────────┘
```

**Layer Overview:**

| Layer | Responsibility | Module |
|-------|----------------|--------|
| **User Layer** | User interaction entry point | - |
| **Agent Layer** | Core control, ReAct loop | `agent/` |
| **Infrastructure** | Independent modules | `model/` `memory/` `tool/` |
| **Schema Layer** | Pydantic data structures | `model/schema.py` |

## Project Structure

```
terminal_bench/
├── agent/                  # Agent layer
│   ├── base.py             # BaseAgent abstract class
│   ├── tool_agent.py       # ToolAgent (tool calling support)
│   └── react_agent.py      # ReactAgent (ReAct loop)
├── model/                  # Model layer
│   ├── base.py             # BaseLLM abstract class
│   ├── litellm_model.py    # LiteLLM implementation
│   └── schema.py           # Message, ToolCall, LLMResponse
├── memory/                 # Memory layer
│   ├── base.py             # BaseMemory abstract class
│   ├── sliding_window.py   # Sliding window strategy
│   └── summary.py          # Auto-summarization strategy
├── tool/                   # Tool layer
│   ├── base.py             # Tool Protocol
│   └── manager.py          # ToolManager + @register_tool
├── pipeline/               # DAG Pipeline
│   └── base.py             # BaseNode, BasePipeline, NodeContext
├── prompt/                 # Prompt templates
├── config/                 # Configuration management
├── debug/                  # Debug utilities (colored logs)
└── test/                   # Tests
```

## Quick Start

### 1. Configuration

#### Option 1: Environment Variable (Recommended)

Copy `.example_env` to `.env` and set your custom config path:

```bash
cp .example_env .env
```

```bash
# .env
EA_DEFAULT_CONFIG=/path/to/your/config.yaml
```

#### Option 2: Edit Package Config

```bash
cp config/config_example.yaml config/config.yaml
```

#### Config File Format

```yaml
debug: true
summary_model: gpt-4o-mini

models:
  gpt-4o-mini:
    api_type: openai
    base_url: https://api.openai.com/v1
    api_key: sk-xxx

  # Custom models with cost configuration
  gemini-2.5-flash:
    api_type: openai
    base_url: https://your-proxy.com/v1
    api_key: your-key
    cost:
      input_cost_per_token: 0.0000003
      output_cost_per_token: 0.00000252
      max_tokens: 8192
      max_input_tokens: 1048576
```

**Config Loading Priority:**
1. Path specified by `EA_DEFAULT_CONFIG` environment variable
2. Default `config/config.yaml` in package

### 3. Create Agent

```python
import asyncio
from agent.react_agent import ReactAgent
from config.base import ModelConfig
from model.litellm_model import LiteLLMModel

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

### Agent Layer

| Class | Description |
|-------|-------------|
| `BaseAgent` | Abstract base class with model, memory, and history management |
| `ToolAgent` | Extends BaseAgent with tool registration and execution |
| `ReactAgent` | ReAct loop implementation: think → act → observe |

### Model Layer

| Class | Description |
|-------|-------------|
| `BaseLLM` | Abstract interface defining `call()` and `call_with_history()` |
| `LiteLLMModel` | LiteLLM implementation supporting all LiteLLM-compatible models |
| `Message` | Pydantic message model (system/user/assistant/tool) |
| `ToolCall` | Tool call structure |
| `LLMResponse` | Unified response format with content, tool_calls, usage |

### Memory Layer

| Strategy | Use Case | Features |
|----------|----------|----------|
| `SlidingWindowMemory` | Short conversations | Truncate by message/token count, keep recent messages |
| `SummaryMemory` | Long conversations | Auto-summarize and persist, respects max_tokens |

```python
from memory import SlidingWindowMemory, SummaryMemory

# Sliding window: limit by message and token count
memory = SlidingWindowMemory(max_messages=20, max_tokens=4000)

# Auto-summary: for long tasks, max_tokens fetched from litellm
memory = SummaryMemory(
    task_id="task_001",
    reserve_ratio=0.3,
    workspace="workspace",
)
```

### Tool Layer

Tools must implement the `Tool` Protocol:

```python
from typing import Protocol

class Tool(Protocol):
    name: str
    type: str
    description: str

    def init(self) -> None: ...
    def execute(self, **kwargs) -> str: ...
```

## Pipeline

DAG-based workflow orchestration with parallel node execution:

```python
import asyncio
from pipeline.base import BaseNode, BasePipeline, NodeContext

# Define nodes
class FetchData(BaseNode):
    async def execute(self, ctx: NodeContext) -> None:
        ctx.data = "raw_data"

class ProcessA(BaseNode):
    async def execute(self, ctx: NodeContext) -> None:
        ctx.result_a = f"{ctx.data}_processed_A"

class ProcessB(BaseNode):
    async def execute(self, ctx: NodeContext) -> None:
        ctx.result_b = f"{ctx.data}_processed_B"

class Merge(BaseNode):
    async def execute(self, ctx: NodeContext) -> None:
        ctx.final = f"{ctx.result_a} + {ctx.result_b}"

# Build DAG using >> syntax
fetch = FetchData()
process_a = ProcessA()
process_b = ProcessB()
merge = Merge()

fetch >> [process_a, process_b]  # Parallel branches
process_a >> merge
process_b >> merge

# Execute
pipeline = BasePipeline(root=fetch)
ctx = asyncio.run(pipeline.run())
print(ctx.final)  # "raw_data_processed_A + raw_data_processed_B"

# Visualize (Mermaid format)
print(pipeline.visualize())
```

**Core Components:**

| Component | Description |
|-----------|-------------|
| `BaseNode` | Abstract node class, implement `execute(ctx)` |
| `BasePipeline` | Pipeline executor with level-based parallel execution |
| `NodeContext` | Shared context for inter-node data passing |
| `>>` operator | Syntactic sugar for `node.add(successor)` |

## Debugging

Enable debug mode for colored logs:

```yaml
# config/config.yaml
debug: true
```

Log output example:
```
14:30:15 DEBUG [ReactAgent] User: What's the weather?
14:30:15 DEBUG [ReactAgent] Iteration 1/10
14:30:16 INFO  [LiteLLM] Response: in=150, out=45, cost=$0.000195
14:30:16 INFO  [ReactAgent] Tool call: get_weather({"city": "Beijing"})
14:30:16 INFO  [ReactAgent] Tool result: The weather in Beijing is sunny, 25°C.
14:30:17 INFO  [ReactAgent] Final: The weather in Beijing is sunny with 25°C.
```

Use `LogCollector` to capture logs:

```python
from debug.log import LogCollector, Logger

log = Logger("MyApp")

with LogCollector() as collector:
    log.info("Step 1")
    log.info("Step 2")

print(collector.to_text())  # "Step 1\nStep 2"
```

## Running Tests

```bash
python -m test.test_agent
python -m test.test_model
```

## Acknowledgements

Thanks to [litellm](https://github.com/BerriAI/litellm) and [OpenManus](https://github.com/FoundationAgents/OpenManus.git) for inspiration and guidance.

## License

[MIT License](LICENSE) © 2025 Yiran Peng

### 2. Define Tools

Use the `@register_tool` decorator:

```python
from tool import register_tool

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
        """Called when tool is initialized"""
        pass

    def execute(self, city: str) -> str:
        """Execute tool logic"""
        return f"The weather in {city} is sunny, 25°C."
```

