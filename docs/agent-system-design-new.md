# EasyAgent 渐进式设计文档

> 这份文档描述 EasyAgent 的**演进路径**,不是一次性设计出来的完整架构蓝图。
>
> 项目按自然需求推进:每一步都有明确的"为什么要做这个",每一步的产出都能直接被下一步增量使用。抽象不是预先设计的,是从实际需求中长出来的。
>
> 阅读方式:按阶段顺序读,你会看到整个框架是如何一块一块拼起来的。每一阶段结束后代码都是**可运行的**,不是半成品。

---

## 总览

| 阶段 | 主题 | 驱动需求 | 产出抽象 | 状态 |
|---|---|---|---|---|
| 1 | 接入 LLM | 需要和大模型对话 | `BaseLLM` + `LiteLLMModel` | ✅ 已完成 |
| 2 | 最简 Agent | 循环 + prompt 构造一个能用 Agent | `BaseAgent`(含硬编码循环) | ✅ 已完成 |
| 3 | Loop 抽象化 | 不止 ReAct 一种推理模式 | `BaseLoop` | 🔲 待重构 |
| 4 | Memory + Context | 管理聊天记录和模型窗口 | `BaseMemory` + `BaseContext` | ⚠️ 部分完成,需分离 |
| 5 | Tools | 让 Agent 能执行动作 | `Tool` protocol + `ToolManager` | ✅ 已完成 |
| 6 | Skills | 工具多了之后渐进式披露 | `Skill` + `SkillManager` + `load_skill` | ✅ 已完成 |
| 7 | MCP | 接入外部工具生态 | `MCPClient` + `MCPTool` | 🔲 未开始 |
| 8 | Sandbox | 安全执行代码/命令 | `BaseSandbox` + `DockerSandbox` | ✅ 已完成 |
| 9 | 统一管理(Capability) | 能力多了如何组织 | `BaseCapability` + 各能力迁移 | 🔲 未开始 |
| 10 | 多 Agent(未来) | 协作类任务的真实需求 | `Session` + `PeerCapability` | 🔲 预留扩展点 |

---

## 阶段 1:接入 LLM

### 需求

做 Agent 的第一步必然是**和大模型说话**。但大模型提供商众多——OpenAI、Anthropic、Gemini、DeepSeek 等等——各家 SDK 不一样。如果每换一家都要改业务代码,项目就废了。

### 设计

定义一个统一的 `BaseLLM` 协议,屏蔽底层差异:

```python
class BaseLLM(ABC):
    @abstractmethod
    async def call(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> LLMResponse: ...

    @abstractmethod
    async def call_with_history(
        self,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> LLMResponse: ...
```

`LLMResponse` 封装所有返回信息,包括 `content`、`tool_calls`、`usage` 等,提供商差异由实现层吸收。

### 实现选型:LiteLLM

不重复造轮子。LiteLLM 已经把几十家模型统一成 OpenAI 格式了,我们在它上面做薄封装:

```python
class LiteLLMModel(BaseLLM):
    def __init__(self, model: str, api_base: str | None = None,
                 api_key: str | None = None, **kwargs):
        ...

    async def call_with_history(self, messages, tools=None, **kw):
        resp = await litellm.acompletion(
            model=self.model, messages=messages, tools=tools, **kw
        )
        return self._normalize(resp)
```

### 本阶段产出

- `easyagent/model/base.py` — `BaseLLM` 协议
- `easyagent/model/schema.py` — `Message`, `LLMResponse`, `ToolCall`
- `easyagent/model/litellm_model.py` — `LiteLLMModel` 实现

**现在可以做的事**:

```python
model = LiteLLMModel(model="gpt-4o-mini")
resp = await model.call("写首诗")
print(resp.content)
```

这是一个**可用的** LLM 调用层,不依赖 Agent 的任何东西。下一阶段直接拿来用。

---

## 阶段 2:最简 Agent(硬编码循环)

### 需求

有了 LLM 就能做问答,但**单次问答不等于 Agent**。Agent 的核心是"能根据任务循环、能调工具、能自己判断什么时候结束"。

最简单的循环:ReAct 模式——think / act / observe,直到模型说"我完成了"。

### 设计

写一个 `ReactAgent`,内部硬编码 ReAct 循环:

```python
class ReactAgent:
    REACT_END_TOKEN = "<<REACT_COMPLETE>>"

    def __init__(self, model: BaseLLM, system_prompt: str,
                 max_iterations: int = 10):
        self._model = model
        self._system = REACT_SYSTEM_PROMPT + "\n\n" + system_prompt
        self._max = max_iterations
        self._history: list[Message] = []

    async def run(self, user_input: str) -> str:
        self._history.append(Message.user(user_input))

        for i in range(self._max):
            msgs = [Message.system(self._system)] + self._history
            response = await self._model.call_with_history(msgs)

            if self.REACT_END_TOKEN in response.content:
                answer = response.content.split(self.REACT_END_TOKEN)[0].strip()
                self._history.append(Message.assistant(answer))
                return answer

            self._history.append(Message.assistant(response.content))

        return "Max iterations reached"
```

### 为什么是硬编码?

**这是故意的**。在只有一个循环模式的时候,不需要抽象。提前抽象就是过度设计。

### 本阶段产出

- `easyagent/agent/base.py` — `BaseAgent`(持有 model、system、history)
- `easyagent/agent/react_agent.py` — `ReactAgent`(硬编码 ReAct 循环)
- `easyagent/prompt/react.py` — ReAct 提示词模板

**现在可以做的事**:

```python
agent = ReactAgent(
    model=LiteLLMModel("gpt-4o-mini"),
    system_prompt="你是一个有用的助手。",
)
answer = await agent.run("介绍下你自己")
```

完整可用的对话 Agent。下一阶段在此基础上扩展。

---

## 阶段 3:Loop 抽象化

### 需求

跑过一段时间后会发现:

- 简单问答不需要 ReAct,一次调用就返回最好(`SingleTurnLoop`)
- 复杂任务更适合先规划再执行(`PlanActLoop`)
- 未来还可能要流式输出(`StreamingLoop`)、多模型投票(`EnsembleLoop`)

现在循环逻辑埋在 `ReactAgent` 里,想换个推理模式就得复制一遍 `run()`。**现在才到了需要抽象 Loop 的时候**。

### 设计

把推理策略抽出来:

```python
class BaseLoop(ABC):
    @abstractmethod
    async def run(self, agent: BaseAgent, user_input: Any) -> str:
        ...

    def is_finished(self, agent, response) -> bool:
        return False
```

Agent 变成**编排者**,持有一个 Loop:

```python
class BaseAgent:
    def __init__(self, model, loop: BaseLoop, system_prompt=""):
        self._model = model
        self._loop = loop
        self._system_prompt = system_prompt
        self._history: list[Message] = []

    async def run(self, user_input):
        return await self._loop.run(self, user_input)
```

Loop 通过 `agent` 公开接口工作,不自己持有状态。`ReactAgent` 保留,但变成 `Agent + ReActLoop` 的 preset:

```python
class ReActLoop(BaseLoop):
    def __init__(self, max_iterations=10, end_token="<<REACT_COMPLETE>>"):
        ...
    async def run(self, agent, user_input):
        agent.add_message(Message.user(user_input))
        for _ in range(self._max_iterations):
            response = await agent._model.call_with_history(agent._history)
            if self._end_token in response.content:
                ...
```

### 本阶段产出

- `easyagent/loop/base.py` — `BaseLoop`
- `easyagent/loop/react.py` — `ReActLoop`
- `easyagent/loop/single.py` — `SingleTurnLoop`
- `easyagent/agent/base.py` — 重构为编排者
- `ReactAgent` 保留为向后兼容的 preset

**现在可以做的事**:

```python
# 默认 ReAct
agent = Agent(model=model, loop=ReActLoop())

# 或单轮问答
agent = Agent(model=model, loop=SingleTurnLoop())
```

Loop 可替换,Agent 其他部分不变。下一阶段开始处理历史存储问题。

---

## 阶段 4:Memory + Context(职责分离)

### 需求

Agent 跑几轮就会遇到两个问题:

1. 对话历史越来越长,模型上下文窗口装不下
2. 即使装得下,把所有历史都传给模型也很贵,且老消息对当前任务不重要

**最初的直觉**:搞一个 `Memory` 类,既存消息也负责截断。

但这样做很快就暴露问题:

- `SummaryMemory` 把老消息摘要后**覆盖掉原始消息**——历史丢了,调试难
- 想换策略(滑动窗口 → 摘要)就得换整个 Memory 实现,**原始记录不兼容**
- Memory 既管存储又管模型输入,**两件事被绑在一起**

### 设计:两个职责拆开

**Memory**:忠实的记录者。只管存,永不丢:

```python
class BaseMemory(ABC):
    @abstractmethod
    def add(self, msg: Message) -> None: ...

    @abstractmethod
    def get_all(self) -> list[Message]: ...

    @abstractmethod
    def clear(self) -> None: ...
```

**Context**:从 Memory 组装送给模型的窗口。这里才有"策略":

```python
class BaseContext(ABC):
    @abstractmethod
    def build(
        self,
        memory: BaseMemory,
        system_prompt: str,
    ) -> list[dict[str, Any]]: ...
```

具体 Context 实现:

| 实现 | 策略 |
|---|---|
| `FullContext` | 全量,不裁剪 |
| `SlidingWindowContext` | 最近 N 条 / N tokens |
| `SummaryContext` | 老消息 LLM 摘要 + 最近 M 条完整 |
| `RAGContext`(未来) | 按 query 向量检索 |

### 关键约束

**摘要只缓存在 Context 内,永不写回 Memory**:

```python
class SummaryContext(BaseContext):
    def __init__(self, summary_model: BaseLLM, reserve_recent: int = 10):
        self._model = summary_model
        self._reserve = reserve_recent
        self._cached_summary: str | None = None
        self._summarized_upto: int = 0

    def build(self, memory, system_prompt):
        all_msgs = memory.get_all()          # Memory 始终完整
        recent = all_msgs[-self._reserve:]
        old = all_msgs[:-self._reserve]

        if len(old) > self._summarized_upto:
            self._cached_summary = self._summarize(old)
            self._summarized_upto = len(old)

        # 组装 system + summary + recent
        ...
```

这样无论 Context 策略怎么换,Memory 里始终是完整的原始历史,可以随时切换策略或重新摘要。

### Agent 如何使用

```python
class BaseAgent:
    def __init__(self, model, loop, memory=None, context=None, system_prompt=""):
        self.memory = memory or InMemoryMemory()
        self.context = context or SlidingWindowContext()
        ...

    def add_message(self, msg: Message) -> None:
        self.memory.add(msg)

    def get_model_messages(self) -> list[dict]:
        return self.context.build(self.memory, self._system_prompt)
```

Loop 调 `agent.add_message()` 和 `agent.get_model_messages()`,不再碰 `_history` 列表。

### 本阶段产出

- `easyagent/memory/base.py` — `BaseMemory`
- `easyagent/memory/inmemory.py` — `InMemoryMemory`
- `easyagent/context/base.py` — `BaseContext`
- `easyagent/context/full.py`, `sliding.py`, `summary.py`
- 移除旧的 `SlidingWindowMemory` / `SummaryMemory`(职责已拆开)

**现在可以做的事**:

```python
agent = Agent(
    model=model,
    loop=ReActLoop(),
    memory=InMemoryMemory(),
    context=SummaryContext(summary_model=cheap_model, reserve_recent=10),
)
```

Memory 和 Context 可以独立替换。未来加 `FileMemory` / `RAGContext` 都不影响其他组件。

---

## 阶段 5:Tools(让 Agent 执行动作)

### 需求

到目前为止 Agent 只会说话。真实任务需要它能**查天气、搜网页、算数、读写文件**——也就是调用工具。

OpenAI 的 tool calling 已经是行业标准:模型返回 `tool_calls`,调用方执行,把结果塞回对话。

### 设计

**Tool 协议**:任何满足这个形状的类都是 tool:

```python
@runtime_checkable
class Tool(Protocol):
    name: str
    type: str          # "function"
    description: str
    parameters: dict   # JSON Schema

    def init(self) -> None: ...
    def execute(self, **kwargs) -> str: ...
```

**注册机制**:装饰器 + 自动发现:

```python
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

    def init(self): pass

    def execute(self, city: str) -> str:
        return f"The weather in {city} is sunny."
```

**ToolManager 单例**:进程级注册表,用 `pkgutil` 自动扫描 `easyagent/tool/` 下所有文件:

```python
class ToolManager:
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def get_schema(self, names: list[str]) -> list[dict]: ...
```

### Agent 集成

Agent 持有一个 `enabled_tools: list[str]`——只有列表中的 tool 才会被暴露给 LLM:

```python
class BaseAgent:
    def __init__(self, model, loop, tools: list[str] = None, ...):
        ...
        self.enabled_tools = tools or []

    def get_tool_schemas(self) -> list[dict]:
        return ToolManager().get_schema(self.enabled_tools)

    async def execute_tool(self, name: str, args: dict) -> str:
        tool = ToolManager().get(name)
        if tool is None or name not in self.enabled_tools:
            return f"Tool '{name}' not available"
        return await _call_tool(tool, args)
```

Loop 里加上 tool call 处理:

```python
# ReActLoop.run 内
response = await model.call(messages, tools=agent.get_tool_schemas())
for tc in response.tool_calls or []:
    result = await agent.execute_tool(tc.name, tc.arguments)
    agent.add_message(Message.tool(result, tc.id))
```

### 本阶段产出

- `easyagent/tool/base.py` — `Tool` protocol
- `easyagent/tool/manager.py` — `ToolManager` + `@register_tool` + 自动发现
- `easyagent/tool/code/` — 内置工具(`bash`, `read_file`, `write_file`)
- `easyagent/tool/web/` — 内置工具(`serper_search`)
- Agent 新增 `enabled_tools` / `execute_tool` / `get_tool_schemas`

**现在可以做的事**:

```python
agent = Agent(
    model=model,
    loop=ReActLoop(),
    tools=["get_weather", "calculate"],
)
answer = await agent.run("北京天气几度?")
```

Agent 真正能做任务了。下一阶段解决"工具太多"的问题。

---

## 阶段 6:Skills(渐进式披露)

### 需求

工具越来越多之后,两个问题浮现:

1. System prompt 臃肿:几十个工具的 description 都塞进去,token 费用高、模型注意力分散
2. 某些任务需要"**指令 + 工具组合**"作为一个整体。比如"数据分析"包括 pandas 相关工具 + 一套完整的分析流程说明。光给工具不给上下文,LLM 不知道怎么用

**解决方案**:Skills。把"能力包"作为一个整体(markdown 指令 + 工具白名单),LLM 按需加载。

### 设计:渐进式披露

**Skill 定义**:markdown 文件 + YAML frontmatter:

```markdown
---
name: data-analysis
description: Pandas-based CSV analysis workflow.
allowed-tools:
  - read_file
  - python_eval
---

# Data Analysis Skill

When a user asks for CSV analysis:
1. Read the file with `read_file`
2. Use `python_eval` with pandas to compute statistics
3. Return insights in natural language
```

**工作流程**:

1. Agent 启动时,只把 skill 的 **name + description** 注入 system prompt
2. LLM 看到"Available Skills"清单,决定需要时调用 `load_skill(name="data-analysis")`
3. `load_skill` 返回完整正文,并激活该 skill 声明的工具
4. LLM 看到完整指令 + 新工具可用,继续执行

### 实现

- `SkillManager` 类似 `ToolManager`,扫描 `./skills/` 目录
- `@register_tool class LoadSkill` 实现 `load_skill` 工具
- Agent 有 `loaded_skills: list[str]`

```python
agent = Agent(
    model=model,
    loop=ReActLoop(),
    tools=["some_tool"],
    skills=["data-analysis", "web-scraping"],
    skill_dir="./skills",
)
```

System prompt 里自动追加:

```
## Available Skills
- **data-analysis**: Pandas-based CSV analysis workflow.
- **web-scraping**: Fetch and parse web pages.
```

LLM 调 `load_skill` 时:
- `SkillManager` 读取 body 返回
- Skill 声明的 tools 加到 `agent.enabled_tools`
- Body 作为 tool result 进入对话历史

### 本阶段产出

- `easyagent/skill/base.py` — `Skill`, `SkillMeta`
- `easyagent/skill/loader.py` — 解析 SKILL.md
- `easyagent/skill/manager.py` — `SkillManager` 单例
- `easyagent/tool/skill/load_skill.py` — 内置 `load_skill` 工具

**现在可以做的事**:

```python
agent = Agent(
    model=model,
    loop=ReActLoop(),
    skills=["data-analysis"],
    skill_dir="./skills",
)
answer = await agent.run("分析 sales.csv 的季度趋势")
# LLM 会自动: load_skill → read_file → python_eval → 给出结论
```

---

## 阶段 7:MCP(接入外部工具生态)

### 需求

工具不应该只来自本地 `@register_tool`。**MCP(Model Context Protocol)** 是 Anthropic 主推的标准,让任何程序都可以暴露工具、资源、提示词给 Agent 使用。

接入 MCP 意味着:

- 可以直接用别人写好的工具服务(GitHub、Slack、数据库等)
- 可以把本地能力暴露给其他 Agent 框架
- 生态打通

### 设计:把 MCP 当作 Tool 子类型

**关键观察**:MCP server 暴露的 tool 和本地 tool 在**调用面**上是一样的(name + args → string)。所以不需要新的顶层抽象,只需要让 `ToolManager` 能容纳 MCP tool。

```python
class MCPClient:
    """管理到某个 MCP server 的连接。"""
    async def connect(self, config: MCPServerConfig): ...
    async def list_tools(self) -> list[MCPToolInfo]: ...
    async def call_tool(self, name: str, args: dict) -> str: ...


class MCPTool:
    """把 MCP server 的一个 tool 包装成满足 Tool Protocol 的对象。"""
    def __init__(self, client: MCPClient, info: MCPToolInfo):
        self.name = info.name
        self.description = info.description
        self.parameters = info.input_schema
        self._client = client

    async def execute(self, **kwargs) -> str:
        return await self._client.call_tool(self.name, kwargs)
```

**注册**:

```python
mcp_client = MCPClient()
await mcp_client.connect({"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]})

for info in await mcp_client.list_tools():
    ToolManager().register(MCPTool(mcp_client, info))
```

注册完成后,`agent.enabled_tools=["github_create_issue"]` 就能直接用,对 Agent / Loop 完全透明。

### 本阶段产出(计划)

- `easyagent/mcp/client.py` — `MCPClient`
- `easyagent/mcp/tool.py` — `MCPTool`
- `easyagent/mcp/__init__.py` — 便捷函数 `register_mcp_server(config)`

**现在可以做的事**:

```python
await register_mcp_server({
    "name": "github",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
})

agent = Agent(
    model=model,
    loop=ReActLoop(),
    tools=["github_create_issue", "github_list_prs"],
)
```

外部工具和本地工具一视同仁。

---

## 阶段 8:Sandbox(安全执行)

### 需求

到阶段 5 已经有 `bash` 工具了,但它**直接在本地进程执行**——对开发环境是灾难(一条 `rm -rf /` 就完蛋)。生产环境更不能接受。

需要隔离:容器里跑、资源限制、网络受控。

**不同场景需要不同 Sandbox**:

| 场景 | 合适的 Sandbox |
|---|---|
| 开发调试 | LocalSandbox(隔离的临时目录) |
| 生产单机 | DockerSandbox |
| Serverless / 共享 | E2B(云沙箱) |
| K8s 集群 | KubernetesSandbox(未来) |

### 设计

**BaseSandbox 抽象**:

```python
class BaseSandbox(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def exec_command(self, cmd: str, **kw) -> ExecResult: ...

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    async def read_file(self, path: str) -> str: ...
```

**优先实现 DockerSandbox**(最通用):

```python
class DockerSandbox(BaseSandbox):
    def __init__(self, image="python:3.12-slim", memory_limit="512m",
                 cpu_limit=1.0, network=True):
        ...

    async def start(self):
        self._container = docker.run(
            self.image,
            mem_limit=self.memory_limit,
            cpu_period=100000,
            cpu_quota=int(self.cpu_limit * 100000),
            network_mode="bridge" if self.network else "none",
            ...
        )
```

**LocalSandbox 作为开发 fallback**:临时目录 + 子进程。

### Tool 如何用 Sandbox?

这里有个设计问题:`bash` / `read_file` / `write_file` 需要一个沙箱实例才能工作。怎么传给 tool?

**当前方案**(v1):用 ContextVar:

```python
_current_sandbox: ContextVar[BaseSandbox | None] = ContextVar("sandbox", default=None)

class BashTool:
    async def execute(self, command: str) -> str:
        sandbox = _current_sandbox.get()
        return (await sandbox.exec_command(command)).output
```

Agent 启动沙箱时把它塞进 ContextVar,工具运行时读出来用。`SandboxAgent` 包装这个生命周期:

```python
class SandboxAgent(ReactAgent):
    async def run(self, user_input):
        async with self._sandbox:
            with sandbox_context(self._sandbox):
                return await super().run(user_input)
```

**这个方案能用,但不漂亮**——ContextVar 是隐式依赖,SandboxAgent 为了管理这件事成了一个独立的 Agent 子类。这个技术债在**阶段 9** 会清理。

### 本阶段产出

- `easyagent/sandbox/base.py` — `BaseSandbox`, `ExecResult`
- `easyagent/sandbox/impl.py` — `DockerSandbox`, `LocalSandbox`
- `easyagent/agent/sandbox_agent.py` — `SandboxAgent`(临时方案)

**现在可以做的事**:

```python
agent = SandboxAgent(
    model=model,
    sandbox=DockerSandbox(image="python:3.12-slim"),
)
await agent.run("用 Python 算斐波那契前 20 项并运行")
```

---

## 阶段 9:统一管理(Capability 抽象)

### 需求

走到这里,Agent 身上已经挂了一堆东西:

- 基础:model、loop、memory、context、system_prompt
- tools(通过 `enabled_tools` 列表)
- skills(通过 `skills` 参数 + ContextVar hack)
- sandbox(通过 `SandboxAgent` 子类 + ContextVar)

**问题暴露**:

1. **扩展方式不统一**
   - 加 tool → `agent.enabled_tools.append(...)`
   - 加 skill → Agent 构造器新增 `skills` 参数 + 生成 system prompt 片段 + 注册 `load_skill` + 维护 `loaded_skills`
   - 加 sandbox → 新写一个 Agent 子类(`SandboxAgent`)

   想再加一个能力(比如"审批拦截"、"审计日志"、"权限控制"),不知道走哪条路。

2. **生命周期管理散落**
   - Sandbox 需要 `on_enter` 启动 / `on_exit` 停止
   - Skills 的 `load_skill` 需要在 tool_call 时拦截
   - 没有统一位置,每种能力都自己搞一套

3. **`SandboxAgent` 是子类爆炸的前兆**
   - 想要 "Sandbox + 审批" 怎么办?写 `ApprovalSandboxAgent`?
   - 组合爆炸。

**现在是时候统一能力管理模型了**。

### 核心观察

Tools / Skills / Sandbox / 审批 / 追踪 / 权限 —— 这些东西在形态上有共性:

- 都是**可选**的(不是每个 Agent 都要)
- 都可能需要**启动/停止**(沙箱、MCP 连接)
- 都可能向 system prompt **贡献片段**(skills 的清单、tools 的说明)
- 都可能**影响 tool 执行**(skills 的 load_skill 拦截、审批的 yes/no、权限的白名单)
- 都可能**暴露 tool**(skills 暴露 load_skill,ToolCapability 暴露注册的 tool)

**这就是 Capability 的形状**。

### 设计:`BaseCapability`

```python
class BaseCapability(ABC):
    # 生命周期
    def on_attach(self, agent: BaseAgent) -> None: pass
    async def on_enter(self, agent: BaseAgent) -> None: pass
    async def on_exit(self, agent: BaseAgent) -> None: pass

    # 贡献 system prompt
    def get_system_prompt_parts(self, agent: BaseAgent) -> list[str]:
        return []

    # 贡献默认工具(写入 agent.enabled_tools)
    def get_default_tools(self) -> list[str]:
        return []

    # 拦截/执行 tool call(first non-None wins)
    async def handle_tool_call(
        self, agent: BaseAgent, name: str, args: dict,
    ) -> str | None:
        return None
```

所有 hook **都是可选的**,默认空实现。具体 Capability override 需要的 hook。

### 迁移:把已有能力都收拢到 Capability

**ToolCapability**(唯一有权真正执行 tool):

```python
class ToolCapability(BaseCapability):
    def __init__(self, tools: list[str]):
        self._default_tools = tools

    def on_attach(self, agent):
        for t in self._default_tools:
            if t not in agent.enabled_tools:
                agent.enabled_tools.append(t)

    async def handle_tool_call(self, agent, name, args):
        tool = ToolManager().get(name)
        if tool is None or name not in agent.enabled_tools:
            return None
        return await _call_tool(tool, args)
```

**SandboxCapability**(只提供资源,不管 tool):

```python
class SandboxCapability(BaseCapability):
    def __init__(self, sandbox: BaseSandbox):
        self._sandbox = sandbox

    async def on_enter(self, agent):
        await self._sandbox.start()
        agent.resources["sandbox"] = self._sandbox

    async def on_exit(self, agent):
        await self._sandbox.stop()
        agent.resources.pop("sandbox", None)
```

Tool 通过 `agent.resources["sandbox"]` 取沙箱,**不再需要 ContextVar**。

**SkillCapability**(接管 load_skill,不再需要独立注册 tool):

```python
class SkillCapability(BaseCapability):
    def __init__(self, skills: list[str], skill_dir=None):
        ...

    def on_attach(self, agent):
        SkillManager().add_search_dir(self._skill_dir)
        if "load_skill" not in agent.enabled_tools:
            agent.enabled_tools.append("load_skill")

    def get_system_prompt_parts(self, agent):
        summaries = SkillManager().list_summaries(self._skill_names)
        return [build_skills_section(summaries)] if summaries else []

    async def handle_tool_call(self, agent, name, args):
        if name != "load_skill":
            return None
        # ... 处理加载逻辑,激活 tools
```

### Agent 变成薄编排者

```python
class Agent:
    def __init__(
        self,
        model: BaseLLM,
        loop: BaseLoop,
        capabilities: list[BaseCapability] = None,
        memory: BaseMemory = None,
        context: BaseContext = None,
        system_prompt: str = "",
    ):
        self._model = model
        self._loop = loop
        self._capabilities = capabilities or []
        self.memory = memory or InMemoryMemory()
        self.context = context or SlidingWindowContext()
        self._system_prompt = system_prompt
        self.enabled_tools = []
        self.loaded_skills = []
        self.resources = {}

        for cap in self._capabilities:
            cap.on_attach(self)

    async def run(self, user_input):
        try:
            for cap in self._capabilities:
                await cap.on_enter(self)
            return await self._loop.run(self, user_input)
        finally:
            for cap in reversed(self._capabilities):
                await cap.on_exit(self)

    async def execute_tool(self, name, args):
        for cap in self._capabilities:
            result = await cap.handle_tool_call(self, name, args)
            if result is not None:
                return result
        return f"Tool '{name}' not handled"

    def build_system_prompt(self):
        parts = [self._system_prompt]
        for cap in self._capabilities:
            parts += cap.get_system_prompt_parts(self)
        return "\n\n".join(p for p in parts if p)
```

### 装配示例

```python
agent = Agent(
    model=model,
    loop=ReActLoop(),
    capabilities=[
        SandboxCapability(DockerSandbox()),
        ToolCapability(tools=["bash", "read_file", "write_file"]),
        SkillCapability(skills=["data-analysis"]),
    ],
)
```

想再加权限控制?新写一个 Capability,不改 Agent:

```python
class AuthCapability(BaseCapability):
    def __init__(self, allowed_tools: list[str]):
        self._allowed = set(allowed_tools)

    async def handle_tool_call(self, agent, name, args):
        if name not in self._allowed:
            return f"Error: tool '{name}' not permitted"
        return None  # 允许,交给 ToolCapability

# 放在 ToolCapability 之前
agent = Agent(
    ...,
    capabilities=[
        AuthCapability(allowed_tools=["read_file"]),
        ToolCapability(tools=["bash", "read_file", "write_file"]),
    ],
)
```

### 清理的旧代码

- 删 `easyagent/agent/tool_agent.py`(能力归 ToolCapability)
- 删 `easyagent/agent/sandbox_agent.py`(能力归 SandboxCapability,变成薄 preset)
- 删 `easyagent/skill/` 中的 `agent_context` / `get_active_agent`(不再需要 ContextVar)
- 删 `easyagent/sandbox/__init__.py` 中的 `sandbox_context` / `get_sandbox`(改走 `agent.resources`)
- 删 `easyagent/tool/skill/load_skill.py`(逻辑归 `SkillCapability.handle_tool_call`)

### 向后兼容

保留 `ReactAgent` 作为 preset,内部自动装配 Capability:

```python
class ReactAgent(Agent):
    def __init__(self, model, tools=None, skills=None, sandbox=None, **kw):
        caps = []
        if sandbox:
            caps.append(SandboxCapability(sandbox))
        caps.append(ToolCapability(tools=tools or []))
        if skills:
            caps.append(SkillCapability(skills=skills))
        super().__init__(model=model, loop=ReActLoop(),
                         capabilities=caps, **kw)
```

用户代码不变,内部实现干净了。

### 本阶段产出

- `easyagent/capability/base.py` — `BaseCapability`
- `easyagent/capability/tool.py` — `ToolCapability`
- `easyagent/capability/sandbox.py` — `SandboxCapability`
- `easyagent/capability/skill.py` — `SkillCapability`
- Agent 重构为薄编排者
- 旧代码清理

**这一阶段是整个项目的拐点**。从"积木越堆越乱"变成"每个能力职责清晰、组合自由"。

---

## 阶段 10(未来):多 Agent 协作

### 什么时候做?

**只有当多 Agent 协作成为真实业务需求时才做**。过早做会污染 v1 的简洁。

### 什么场景需要?

典型场景:

- 协调者 + 执行者(Planner → Coder → Reviewer)
- 领域专家分工(SQL 专家 + Python 专家 + 文案专家)
- 层级授权(主 Agent + 受限子 Agent)

### 预留扩展点

在阶段 9 的 Capability 模型上**自然扩展**,不需要重构核心:

1. **引入 `Session` 容器**:承载多个 Agent、用户身份、共享附件
2. **新增 `PeerCapability`**:暴露 `ask_peer(agent, message)` tool,让 LLM 调用同 Session 下其他 Agent
3. **单 Agent 路径完全不变**:`agent.run(...)` 不需要显式 Session,隐式创建

关键:**不会破坏现有代码**。v1 用户看不到 Session 这个概念。

### 预期 API

```python
session = Session(user_id="alice")
session.add_agent("planner", planner_agent, primary=True)
session.add_agent("coder", coder_agent)
session.add_agent("reviewer", reviewer_agent)

answer = await session.run("实现并审查一个 TCP 服务器")
# planner 通过 ask_peer 委派给 coder / reviewer
```

详细设计延后到真正需要时再写。

---

## 最终架构全景

经过阶段 1-9 之后的系统结构:

```
┌──────────────────────────────────────────────────────────────┐
│                         Agent                                │
│  (薄编排者:持有 model/loop/capabilities/memory/context)     │
└──────────────────────────────────────────────────────────────┘
     │         │            │              │            │
     ▼         ▼            ▼              ▼            ▼
  ┌─────┐  ┌────────┐  ┌────────┐  ┌────────────┐  ┌─────────┐
  │Model│  │  Loop  │  │ Memory │  │  Context   │  │ Caps[]  │
  └─────┘  │(策略)  │  │ (存储) │  │ (组装策略)  │  │ (能力)  │
           └────────┘  └────────┘  └────────────┘  └─────────┘
                                                      │
              ┌────────┬────────┬───────┬────────┬────┘
              ▼        ▼        ▼       ▼        ▼
          ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
          │Tool  │ │Sand  │ │Skill │ │Auth  │ │...   │
          │Cap   │ │boxCap│ │Cap   │ │Cap   │ │      │
          └──────┘ └──────┘ └──────┘ └──────┘ └──────┘
              │        │        │
              ▼        ▼        ▼
         ┌────────┐ ┌──────┐ ┌──────┐
         │ Tools  │ │Sand- │ │Skills│
         │Manager │ │ box  │ │Mgr   │
         └────────┘ └──────┘ └──────┘
              │
              ├── 本地 @register_tool
              └── MCP tools (阶段 7)
```

---

## 目录结构(最终)

```
easyagent/
├── model/          # 阶段 1 — BaseLLM + LiteLLMModel
├── agent/          # 阶段 2 + 3 + 9 — 薄编排者
│   ├── base.py
│   ├── agent.py
│   └── presets.py  # ReactAgent 兼容
├── loop/           # 阶段 3 — BaseLoop, ReActLoop, SingleTurnLoop
├── memory/         # 阶段 4 — BaseMemory, InMemoryMemory
├── context/        # 阶段 4 — BaseContext, Full/Sliding/Summary
├── tool/           # 阶段 5 — Tool protocol, ToolManager, 内置工具
├── skill/          # 阶段 6 — Skill, SKILL.md 解析
├── mcp/            # 阶段 7 — MCP 接入(未来)
├── sandbox/        # 阶段 8 — BaseSandbox, Docker/Local
├── capability/     # 阶段 9 — BaseCapability + 各具体 Capability
├── session/        # 阶段 10 — 多 Agent 容器(未来,可选)
├── prompt/         # prompt 模板
├── config/         # 配置
└── debug/          # 日志
```

---

## 迁移计划(当前到阶段 9)

项目现状基本在阶段 8 完成,阶段 3、4、9 需要做。按依赖顺序:

**里程碑 A — 抽象 Loop(阶段 3)**
1. 创建 `easyagent/loop/` 模块
2. 把 `ReactAgent.run` 的逻辑搬到 `ReActLoop.run`
3. Agent 改为编排者,通过 `loop.run(agent, input)` 调度
4. 保留 `ReactAgent` 作为 preset,向后兼容

**里程碑 B — Memory / Context 分离(阶段 4)**
1. 创建 `easyagent/context/` 模块,实现 `FullContext` / `SlidingWindowContext` / `SummaryContext`
2. 简化 `easyagent/memory/`,只保留 `InMemoryMemory`
3. Agent 新增 `context` 字段,`get_model_messages()` 走 Context
4. 删除旧的 `SlidingWindowMemory` / `SummaryMemory`

**里程碑 C — Capability 统一(阶段 9)**
1. 创建 `easyagent/capability/` 模块,实现 Base + Tool/Sandbox/Skill 三个具体 Capability
2. Agent 接受 `capabilities=[...]`,重写 `execute_tool` / `build_system_prompt`
3. `ReactAgent` / `SandboxAgent` 改为薄 preset
4. 删除旧代码(`ToolAgent`, `SandboxAgent` 实现体, ContextVar 相关)

**里程碑 D — MCP(阶段 7)**
单独里程碑,不阻塞其他。等 A/B/C 完成后开始。

---

## 总结

### 项目的演进逻辑

1. **每个抽象都有明确需求驱动**——不预先设计
2. **每阶段的产出都是可用的**——不是半成品
3. **上一阶段直接被下一阶段使用**——不返工
4. **抽象只在第二个实现出现时才做**——不过早抽象

### 当前状态到终态的距离

阶段 1、2、5、6、8 已完成,阶段 3、4、9 需要重构,阶段 7、10 是未来新增。里程碑 A/B/C 完成后,项目就进入了"稳定架构"状态,后续新能力(MCP、审批、追踪等)都只是**新增一个 Capability**,不改核心。

### 一句话总结

> **EasyAgent 是一个"每一步都有理由"的项目。Model 让我们能说话,Loop 让我们能循环,Memory 让我们能记住,Context 让我们能筛选,Tool 让我们能行动,Skill 让我们能精炼,Sandbox 让我们能安全,Capability 让所有这些能清晰组合。**
