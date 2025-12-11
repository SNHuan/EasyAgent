# Terminal Bench

轻量级 AI Agent 框架，基于 LiteLLM 构建，支持多模型、工具调用和智能记忆管理。

## 项目结构

```
terminal_bench/
├── agent/                  # Agent 层
│   ├── base.py             # BaseAgent 抽象基类
│   ├── tool_agent.py       # ToolAgent（支持工具调用）
│   └── react_agent.py      # ReactAgent（ReAct 循环实现）
├── model/                  # 模型层
│   ├── base.py             # BaseLLM 抽象基类
│   ├── litellm_model.py    # LiteLLM 实现
│   └── schema.py           # Message, ToolCall, LLMResponse
├── memory/                 # 记忆层
│   ├── base.py             # BaseMemory 抽象基类
│   ├── sliding_window.py   # 滑动窗口（消息数/token 截断）
│   └── summary.py          # Summary（自动摘要压缩）
├── tool/                   # 工具层
│   ├── base.py             # Tool Protocol
│   └── manager.py          # ToolManager + @register_tool
├── prompt/                 # 提示词模板
│   └── memory.py           # Summary 相关提示词
├── config/                 # 配置管理
│   ├── base.py             # AppConfig, ModelConfig
│   └── config.yaml         # 配置文件
├── log.py                  # 日志工具
└── test/                   # 测试
```

## 架构设计

```
BaseAgent (model + memory + history)
    ↓
ToolAgent (+ 工具管理)
    ↓
ReactAgent (ReAct 循环: think → act → observe)
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置模型

编辑 `config/config.yaml`：

```yaml
debug: true
summary_model: gpt-4o-mini

models:
  gpt-4o-mini:
    api_type: openai
    base_url: https://api.openai.com/v1
    api_key: sk-xxx
```

### 3. 定义工具

```python
from tool import register_tool

@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "Get the weather for a city."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str) -> str:
        return f"The weather in {city} is sunny, 25°C."
```

### 4. 创建 Agent

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
)

result = asyncio.run(agent.run("What's the weather in Beijing?"))
print(result)
```

## 记忆管理

### 滑动窗口

```python
from memory import SlidingWindowMemory

memory = SlidingWindowMemory(
    max_messages=20,      # 最多保留 20 条消息
    max_tokens=4000,      # 最多 4000 tokens
)
```

### Summary 自动摘要

```python
from memory import SummaryMemory

memory = SummaryMemory(
    task_id="task_001",   # 任务 ID，用于存储摘要文件
    reserve_ratio=0.3,    # 保留 30% token 给最近消息
)
# max_tokens 自动从 litellm 获取模型上限
# 摘要文件保存在 workspace/task_001/summary.md
```

## Debug 模式

在 `config/config.yaml` 中设置：

```yaml
debug: true
```

开启后会显示：
- LLM 请求/响应详情
- 工具调用和返回结果
- Token 使用和费用统计

## 运行测试

```bash
python -m test.test_agent
python -m test.test_model
```

