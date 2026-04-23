# EasyAgent

[![PyPI version](https://badge.fury.io/py/easy-agent-sdk.svg)](https://badge.fury.io/py/easy-agent-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

[English](README.md) | 中文

EasyAgent 是一个轻量级 Agent 系统，核心围绕几组基础抽象展开：

- `BaseLLM`：模型接入
- `BaseLoop`：执行循环
- `BaseMemory`：完整历史记录
- `BaseContext`：给模型看的上下文组装
- `BaseCapability`：可选能力扩展，例如 tool、skill、sandbox

项目采用渐进式设计：每一层都可以单独使用，上层能力直接建立在下层之上。

## 当前架构

```text
LLM -> Loop -> Memory / Context -> Capability -> Agent
```

关键原则：

- `Agent` 是薄编排者
- `AgentSession` 持有运行态
- `Memory` 永远保存完整历史
- `Context` 决定当前模型看到什么
- `Capability` 用组合而不是子类堆叠来扩展功能

## 特性

- 基于 LiteLLM 的多模型支持
- ReAct / SingleTurn 两类 Loop 抽象
- Memory / Context 职责分离
- `ToolManager` 工具调用
- Skill 渐进式披露
- 通过 Capability 组合 sandbox
- Local / Docker 两种 sandbox 实现

## 安装

```bash
pip install easy-agent-sdk
```

可选依赖：

```bash
pip install easy-agent-sdk[sandbox]
pip install easy-agent-sdk[web]
pip install easy-agent-sdk[all]
```

从源码安装：

```bash
git clone https://github.com/SNHuan/EasyAgent.git
cd EasyAgent
pip install -e ".[dev]"
```

## 配置

准备一个 `config.yaml`：

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

然后设置：

```bash
export EA_DEFAULT_CONFIG=/path/to/config.yaml
```

## 快速开始

最小 `ReactAgent`：

```python
import asyncio

from easyagent import InMemoryMemory, LiteLLMModel, ReactAgent, SlidingWindowContext


async def main() -> None:
    model = LiteLLMModel(model="gpt-4o-mini")
    agent = ReactAgent(
        model=model,
        system_prompt="你是一个简洁可靠的助手。",
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=12),
        max_iterations=5,
    )

    result = await agent.run("用一句话介绍 EasyAgent。")
    print(result)


asyncio.run(main())
```

仓库里也带了一个可直接运行的示例：

```bash
python examples/simple_react_agent.py
```

## Tools

用 `@register_tool` 定义工具：

```python
from easyagent.tool import register_tool


@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "获取城市天气。"
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名"},
        },
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str, **kwargs) -> str:
        return f"{city}天气晴朗。"
```

在 `ReactAgent` 中启用：

```python
agent = ReactAgent(
    model=LiteLLMModel(model="gpt-4o-mini"),
    tools=["get_weather"],
)
```

## Skills

Skill 是按需加载的能力包，格式是 markdown + frontmatter。

目录结构：

```text
./skills/
  my-skill/
    SKILL.md
```

示例：

```markdown
---
name: my-skill
description: 加载前展示给模型的一句话说明。
allowed-tools:
  - get_weather
---

# 完整说明
```

使用方式：

```python
agent = ReactAgent(
    model=LiteLLMModel(model="gpt-4o-mini"),
    skills=["my-skill"],
    skill_dir="./skills",
)
```

模型一开始只会看到 skill 摘要；当它决定加载 skill 时，`SkillCapability` 会返回完整正文，并为当前 session 激活声明的工具。

## Sandbox

现在的 `SandboxAgent` 是一个薄 preset，本质上由下面几层组装而成：

- `SandboxCapability`
- `ToolCapability`
- `ReActLoop`

示例：

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
    result = await agent.run("执行一个简短的 Python 命令并告诉我输出。")
    print(result)


asyncio.run(main())
```

内置 sandbox 工具：

- `bash`
- `write_file`
- `read_file`

## 主要模块

```text
easyagent/
├── agent/       # Agent, ReactAgent, SandboxAgent, AgentSession
├── capability/  # BaseCapability, Tool/Skill/Sandbox capabilities
├── context/     # FullContext, SlidingWindowContext, SummaryContext
├── loop/        # BaseLoop, ReActLoop, SingleTurnLoop
├── memory/      # BaseMemory, InMemoryMemory
├── model/       # BaseLLM, LiteLLMModel, Message, ToolCall
├── sandbox/     # BaseSandbox, DockerSandbox, LocalSandbox
├── skill/       # Skill, SkillManager, SKILL.md 加载
├── tool/        # Tool protocol, ToolManager, 内置工具
├── prompt/      # Prompt 模板
├── config/      # 配置加载
└── debug/       # 日志辅助
```

## 当前状态

当前代码已经切到新架构：

- session 持有运行态
- memory/context 已分离
- 能力通过 capability 组合

MCP 接入和更多文档补充仍然是后续工作。

## 许可证

[MIT License](LICENSE) © 2025 Yiran Peng
