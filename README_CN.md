# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

[English](README.md) | 中文

轻量级 AI Agent 框架，基于 LiteLLM 构建，支持多模型、工具调用、沙箱执行和智能记忆管理。

> **~1200 行代码，完整实现生产级 Agent 能力** — 多模型适配、工具调用、沙箱隔离、智能记忆、ReAct 推理、DAG 流水线、调试追踪。

## 特性

- **多模型支持** - 通过 LiteLLM 统一接口，支持 OpenAI、Anthropic、Gemini 等
- **工具调用** - 基于 Protocol 的工具定义，`@register_tool` 装饰器自动注册
- **沙箱执行** - 支持 Docker 或本地环境的隔离代码执行
- **记忆模块** - 滑动窗口 + 自动摘要两种策略，自动管理上下文长度
- **ReAct 循环** - think → act → observe 标准推理循环
- **DAG Pipeline** - 基于有向无环图的流水线编排，支持节点并行执行
- **调试友好** - 彩色日志输出，token 消耗和成本追踪

## 安装

```bash
pip install easy-agent-sdk
```

**可选依赖：**

```bash
# Docker 沙箱支持
pip install easy-agent-sdk[sandbox]

# Web 工具（SerperSearch）
pip install easy-agent-sdk[web]

# 全部可选依赖
pip install easy-agent-sdk[all]
```

**从源码安装：**

```bash
git clone https://github.com/SNHuan/EasyAgent.git
cd EasyAgent
pip install -e ".[dev]"
```

## 快速开始

### 1. 配置

创建配置文件 `config.yaml`：

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

设置环境变量：

```bash
export EA_DEFAULT_CONFIG=/path/to/config.yaml
```

### 2. 定义工具

```python
from easyagent.tool import register_tool

@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "获取城市天气"
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名"}},
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str) -> str:
        return f"{city}天气晴朗，25°C。"
```

### 3. 创建 Agent

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
    system_prompt="你是一个有帮助的助手。",
    max_iterations=10,
)

result = asyncio.run(agent.run("北京天气怎么样？"))
print(result)
```

### 4. SandboxAgent（代码执行）

```python
import asyncio
from easyagent import SandboxAgent
from easyagent.config import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel

config = ModelConfig.load()
model = LiteLLMModel(**config.get_model("gpt-4o"))

# 本地沙箱（开发用）
agent = SandboxAgent(model=model)

# Docker 沙箱（生产用）
agent = SandboxAgent(
    model=model,
    sandbox_type="docker",
    image="python:3.12-slim",
    cpu_limit=2.0,
    memory_limit="1g",
    network=True,
)

result = asyncio.run(agent.run("写一个斐波那契数列程序并运行"))
print(result)
```

**SandboxAgent** 内置工具：
- `bash` - 执行 shell 命令
- `write_file` - 写入文件（安全处理复杂内容）
- `read_file` - 读取文件

## 核心组件

### Agent

| 类 | 说明 |
|---|------|
| `ReactAgent` | ReAct 循环：think → act → observe |
| `ToolAgent` | 工具注册和执行 |
| `SandboxAgent` | 带隔离代码执行的 ReactAgent |

### Sandbox

```python
from easyagent import DockerSandbox, LocalSandbox, create_sandbox

# 工厂函数
sandbox = create_sandbox("docker", image="python:3.12-slim")

# 或直接实例化
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

# 滑动窗口
memory = SlidingWindowMemory(max_messages=20, max_tokens=4000)

# 自动摘要（长任务）
memory = SummaryMemory(task_id="task_001", reserve_ratio=0.3)
```

### Pipeline

基于 DAG 的流水线，支持并行执行：

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

fetch >> [process_a, process_b]  # 并行分支

pipeline = BasePipeline(root=fetch)
ctx = asyncio.run(pipeline.run())
```

### 内置工具

| 工具 | 说明 | 依赖 |
|------|------|------|
| `bash` | 在沙箱中执行 shell 命令 | SandboxAgent |
| `write_file` | 写入文件到沙箱 | SandboxAgent |
| `read_file` | 从沙箱读取文件 | SandboxAgent |
| `serper_search` | 通过 Serper API 进行 Google 搜索 | `SERPER_API_KEY` 环境变量 |

## 项目结构

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
├── prompt/         # Prompt 模板
└── debug/          # Logger, LogCollector
```

## 许可证

[MIT License](LICENSE) © 2025 Yiran Peng
