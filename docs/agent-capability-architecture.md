# Agent Capability Architecture Design

## Background

The current architecture couples agent features through inheritance:

- `BaseAgent`
- `ToolAgent(BaseAgent)`
- `ReactAgent(ToolAgent)`
- `SandboxAgent(ReactAgent)`

This works for a narrow default path, but it does not scale well once feature combinations diverge. A few examples:

- sandbox + tools, without skills
- tools + custom loop, without ReAct
- skills as optional extension instead of built-in behavior
- one runtime resource shared by multiple capabilities

The root issue is that feature combinations are modeled as agent subclasses rather than as composable capabilities.

At the same time, the preferred implementation style for this project is still abstraction-first: define stable base classes, implement behavior through inheritance, and then assemble the final agent from those implementations.

This document proposes an architecture that preserves that style.

## Design Goals

1. Keep inheritance as the primary implementation mechanism for core abstractions.
2. Make `tool`, `sandbox`, `skills`, and future features optional capabilities instead of fixed agent subclasses.
3. Separate loop behavior from capability behavior.
4. Allow final agents to be assembled declaratively from implementations of base abstractions.
5. Keep the public usage simple for common paths such as ReAct + tools + sandbox.
6. Reduce hidden coupling between prompt construction, tool exposure, runtime resources, and session state.

## Non-Goals

1. This design does not introduce a full plugin system.
2. This design does not solve distributed execution or multi-process orchestration.
3. This design does not attempt to redesign every existing module at once.
4. This design does not require removing convenience entry points like `ReactAgent`.

## Core Idea

The architecture is split into three layers:

1. `BaseAgent`
   A thin orchestrator that owns model, memory, loop, capabilities, and session lifecycle.

2. `BaseLoop`
   A loop strategy abstraction that defines how one agent run progresses.
   Examples: `ReActLoop`, `SingleTurnLoop`, `PlanActLoop`.

3. `BaseCapability`
   A capability abstraction for optional features such as tools, sandbox, skills, tracing, or approvals.

The final agent is assembled from concrete subclasses:

```python
agent = Agent(
    model=model,
    loop=ReActLoop(max_iterations=10),
    capabilities=[
        ToolCapability(tools=["bash", "read_file", "write_file"]),
        SandboxCapability(sandbox=LocalSandbox()),
    ],
    memory=SlidingWindowMemory(),
    system_prompt="You are a helpful assistant.",
)
```

If skills are not needed, `SkillCapability` is simply not included.

## High-Level Structure

```text
BaseAgent
  |- Agent

BaseLoop
  |- ReActLoop
  |- SingleTurnLoop
  |- PlanActLoop

BaseCapability
  |- ToolCapability
  |- SandboxCapability
  |- SkillCapability
  |- PromptCapability
  |- TraceCapability
```

This preserves inheritance where it matters, while moving feature combination to the assembly layer.

## Key Design Principles

### 1. Loop and capability are different kinds of abstractions

`BaseLoop` controls progression.

Typical responsibilities:

- prepare model request
- ask model for next step
- decide whether to continue
- invoke tool execution path
- return final answer

`BaseCapability` does not own the loop. It enriches or constrains runtime behavior through well-defined hooks.

Typical responsibilities:

- contribute system prompt fragments
- expose available tools
- create runtime context resources
- mutate session state in controlled places
- observe lifecycle events

### 2. Session state must be explicit

The agent instance should be mostly configuration.
Mutable run state must live inside `AgentSession`.

### 3. Runtime resources should be shared through session context

Sandbox, loaded skills, trace collector, approval manager, and similar resources should be attached to session context rather than stored implicitly on agent subclasses.

### 4. Capabilities are optional and isolated

If a capability is not assembled into the agent, it should have zero effect on:

- prompt
- tool list
- session state
- runtime lifecycle

This is especially important for skills.

## Core Abstractions

### BaseAgent

`BaseAgent` is the top-level runtime coordinator.

Responsibilities:

- own model, loop, memory, and capabilities
- create a fresh `AgentSession` for each run
- invoke capability lifecycle hooks
- delegate run progression to the loop
- expose minimal public API

Example shape:

```python
from abc import ABC
from typing import Any


class BaseAgent(ABC):
    def __init__(
        self,
        model,
        loop,
        capabilities=None,
        memory=None,
        system_prompt: str = "",
    ):
        self._model = model
        self._loop = loop
        self._capabilities = capabilities or []
        self._memory = memory
        self._system_prompt = system_prompt

    async def run(self, user_input: Any) -> str:
        session = self.create_session(user_input)
        await self._enter_capabilities(session)
        try:
            return await self._loop.run(self, session, user_input)
        finally:
            await self._exit_capabilities(session)
```

Concrete `Agent` can inherit directly from it without adding much logic.

### AgentSession

`AgentSession` holds all mutable runtime state.

Suggested fields:

```python
class AgentSession:
    messages: list[Message]
    enabled_tools: list[str]
    context: dict[str, Any]
    metadata: dict[str, Any]
    final_output: str | None
    iteration_count: int
```

Notes:

- `messages` is the authoritative conversation state.
- `enabled_tools` is the current tool whitelist for the run.
- `context` stores runtime resources such as sandbox or trace collectors.
- `metadata` stores loop-specific or capability-specific annotations.

### BaseLoop

`BaseLoop` defines how the agent progresses from input to output.

Responsibilities:

- build model-facing messages
- decide when a run is complete
- coordinate model calls and tool execution
- write structured outputs back into session

Example abstract shape:

```python
from abc import ABC, abstractmethod
from typing import Any


class BaseLoop(ABC):
    @abstractmethod
    async def run(self, agent: "BaseAgent", session: "AgentSession", user_input: Any) -> str:
        pass

    def build_messages(self, agent: "BaseAgent", session: "AgentSession") -> list[dict[str, Any]]:
        return [m.to_api_dict() for m in session.messages]

    def is_finished(self, session: "AgentSession", response) -> bool:
        return False
```

`BaseLoop` is intentionally powerful. It is the main place where inheritance should express agent behavior styles.

### BaseCapability

`BaseCapability` is the optional behavior extension abstraction.

Responsibilities:

- contribute runtime configuration
- prepare or cleanup resources
- expose prompt fragments
- expose or execute capability-owned actions
- observe loop events

Example abstract shape:

```python
from abc import ABC
from typing import Any


class BaseCapability(ABC):
    def on_attach(self, agent: "BaseAgent") -> None:
        pass

    async def on_enter(self, agent: "BaseAgent", session: "AgentSession") -> None:
        pass

    async def on_exit(self, agent: "BaseAgent", session: "AgentSession") -> None:
        pass

    def get_system_prompt_parts(self, agent: "BaseAgent", session: "AgentSession") -> list[str]:
        return []

    def get_enabled_tools(self, agent: "BaseAgent", session: "AgentSession") -> list[str]:
        return []

    async def before_model_call(
        self,
        agent: "BaseAgent",
        session: "AgentSession",
        request: dict[str, Any],
    ) -> None:
        pass

    async def after_model_call(
        self,
        agent: "BaseAgent",
        session: "AgentSession",
        response: Any,
    ) -> None:
        pass

    async def handle_tool_call(
        self,
        agent: "BaseAgent",
        session: "AgentSession",
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        return None
```

The default implementation does nothing. Concrete capabilities override only what they need.

## Assembly Model

The final runtime behavior is assembled in three steps:

1. Pick one loop implementation.
2. Pick zero or more capability implementations.
3. Build one concrete `Agent`.

This means inheritance defines behavior, while composition defines the final feature set.

That gives both:

- strong abstract base classes
- flexible runtime assembly

## Concrete Capability Design

### ToolCapability

Purpose:

- expose tools to the loop
- render tool schemas
- execute tool calls
- manage dynamic tool enablement during the session

State ownership:

- owns tool registry or tool resolver
- updates `session.enabled_tools`

Responsibilities:

- declare available tools at session startup
- provide tool schema for model calls
- execute tool calls when requested by the loop
- support dynamic enablement by capabilities such as skills

Suggested shape:

```python
class ToolCapability(BaseCapability):
    def __init__(self, registry, tools=None):
        self._registry = registry
        self._default_tools = tools or []

    async def on_enter(self, agent, session):
        for name in self._default_tools:
            if name not in session.enabled_tools:
                session.enabled_tools.append(name)

    def get_tool_schemas(self, session) -> list[dict]:
        ...

    async def handle_tool_call(self, agent, session, tool_name, arguments):
        ...
```

Important design rule:

`ToolCapability` should be the only standard capability that directly executes tool calls. Other capabilities may influence tools, but should not duplicate tool execution logic.

### SandboxCapability

Purpose:

- own sandbox lifecycle
- attach sandbox instance into session context

State ownership:

- `session.context["sandbox"]`

Responsibilities:

- start sandbox on session enter
- stop sandbox on session exit
- expose runtime resource to tools

Suggested shape:

```python
class SandboxCapability(BaseCapability):
    def __init__(self, sandbox):
        self._sandbox = sandbox

    async def on_enter(self, agent, session):
        await self._sandbox.start()
        session.context["sandbox"] = self._sandbox

    async def on_exit(self, agent, session):
        try:
            await self._sandbox.stop()
        finally:
            session.context.pop("sandbox", None)
```

Important design rule:

`SandboxCapability` should not expose tools by itself.

This keeps sandbox and tools orthogonal.

That means:

- `SandboxCapability` provides the resource
- `ToolCapability` exposes `bash`, `read_file`, `write_file`
- the tool implementations pull sandbox from session context

This directly supports the desired combination model.

### SkillCapability

Purpose:

- provide optional skill summaries to the model
- expose `load_skill` only when explicitly enabled
- activate additional tools at runtime

State ownership:

- `session.context["loaded_skills"]`

Responsibilities:

- provide skill summary prompt fragments
- resolve and load skill bodies
- coordinate with `ToolCapability` to enable declared tools

Important design rule:

If `SkillCapability` is absent:

- no skill prompt fragment exists
- no `load_skill` tool is registered
- no skill loading path exists in runtime

This avoids the current architecture problem where skill behavior leaks into the default path.

### PromptCapability

Purpose:

- modular prompt contribution without hardcoding everything into loop classes

Examples:

- persona prompt
- domain policy prompt
- output format prompt

This capability should contribute prompt fragments only. It should not own runtime resources.

### TraceCapability

Purpose:

- collect run events for debug or observability

Examples:

- model requests
- tool calls
- tool outputs
- iteration summaries

This is a good candidate for hook-heavy behavior through `BaseCapability`.

## Loop Design

### ReActLoop

`ReActLoop` is the primary concrete loop for the current project.

Responsibilities:

- append user input to session
- build messages
- ask model for next step
- inspect tool calls
- dispatch tool calls to capability layer
- stop on final answer or max iterations

Suggested shape:

```python
class ReActLoop(BaseLoop):
    def __init__(self, max_iterations: int = 10, end_token: str = "<<REACT_COMPLETE>>"):
        self._max_iterations = max_iterations
        self._end_token = end_token

    async def run(self, agent, session, user_input):
        ...
```

Key point:

The loop should not know what a sandbox is or what a skill is.

It should only know:

- how to ask the model
- how to ask the agent to resolve tool schemas
- how to ask the agent to execute a tool call
- how to stop

### SingleTurnLoop

This loop makes one model call and returns.

Useful for:

- non-tool use cases
- structured output tasks
- lightweight chat mode

### Future Loop Types

The same architecture can support:

- `PlanActLoop`
- `ApproveThenActLoop`
- `StreamingLoop`

without changing capability definitions.

## Agent Responsibilities in This Design

To avoid capability sprawl, `BaseAgent` should expose a small internal contract used by loops:

```python
class BaseAgent(ABC):
    def build_system_prompt(self, session: AgentSession) -> str:
        ...

    def get_tool_schemas(self, session: AgentSession) -> list[dict[str, Any]]:
        ...

    async def execute_tool_call(
        self,
        session: AgentSession,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        ...
```

These methods delegate to capabilities.

This keeps loops simple and keeps capability orchestration centralized.

## Recommended Delegation Rules

### Agent owns

- session creation
- capability attach and lifecycle
- capability dispatch
- shared prompt assembly
- shared tool dispatch entry

### Loop owns

- run progression
- iteration counting
- completion decision
- when the model is called

### Capability owns

- optional behavior
- resource lifecycle
- prompt fragments
- tool exposure or runtime mutation, if relevant

## Prompt Construction Strategy

Prompt construction should not be hardcoded entirely inside `ReActLoop`.

Instead:

1. loop contributes loop-specific instructions
2. agent base prompt is appended
3. capabilities contribute optional fragments

Suggested order:

1. loop prompt
2. agent system prompt
3. capability prompt fragments

This allows:

- ReAct prompt without skills
- ReAct prompt with skills
- domain prompt without touching loop code

## Tool Dispatch Strategy

Tool dispatch should be centralized.

Recommended path:

1. loop sees tool calls in model response
2. loop calls `agent.execute_tool_call(...)`
3. agent asks capabilities in order whether they handle that tool
4. first non-`None` result wins
5. if no capability handles it, return a structured error

This creates clear ownership and avoids tool execution logic spreading through loop subclasses.

Example:

```python
async def execute_tool_call(self, session, tool_name, arguments):
    for capability in self._capabilities:
        result = await capability.handle_tool_call(self, session, tool_name, arguments)
        if result is not None:
            return result
    return f"Tool '{tool_name}' not available"
```

## Example Assemblies

### ReAct + tools only

```python
agent = Agent(
    model=model,
    loop=ReActLoop(max_iterations=10),
    capabilities=[
        ToolCapability(registry=registry, tools=["get_weather", "calculate"]),
    ],
)
```

### ReAct + sandbox + tools, no skills

```python
agent = Agent(
    model=model,
    loop=ReActLoop(max_iterations=10),
    capabilities=[
        SandboxCapability(LocalSandbox()),
        ToolCapability(
            registry=registry,
            tools=["bash", "read_file", "write_file"],
        ),
    ],
)
```

### ReAct + sandbox + tools + skills

```python
agent = Agent(
    model=model,
    loop=ReActLoop(max_iterations=10),
    capabilities=[
        SandboxCapability(LocalSandbox()),
        ToolCapability(
            registry=registry,
            tools=["bash", "read_file", "write_file"],
        ),
        SkillCapability(skill_registry=skill_registry),
    ],
)
```

The difference is explicit and local to assembly.

## Backward Compatibility Strategy

To avoid a disruptive migration, keep convenience wrappers:

### ReactAgent

`ReactAgent` becomes a thin preset:

```python
class ReactAgent(Agent):
    def __init__(self, model, tools=None, skills=None, sandbox=None, **kwargs):
        capabilities = []
        if sandbox is not None:
            capabilities.append(SandboxCapability(sandbox))
        if tools:
            capabilities.append(ToolCapability(registry=ToolRegistry.default(), tools=tools))
        if skills:
            capabilities.append(SkillCapability(skill_registry=SkillRegistry.default(), skills=skills))

        super().__init__(
            model=model,
            loop=ReActLoop(),
            capabilities=capabilities,
            **kwargs,
        )
```

### SandboxAgent

Prefer deprecating it eventually.

Short term:

- keep it as a convenience wrapper
- internally build `Agent(..., capabilities=[SandboxCapability(...), ToolCapability(...)])`

This preserves user ergonomics while cleaning up internals.

## Incremental Refactor Plan

### Phase 1

Introduce the new abstractions without changing public entry points.

Tasks:

- add `AgentSession`
- add `BaseLoop`
- add `BaseCapability`
- add a new generic `Agent`

### Phase 2

Move `ReactAgent` internals into `ReActLoop`.

Tasks:

- shift iteration logic into `ReActLoop`
- move completion logic there
- make agent delegate tool dispatch and prompt assembly

### Phase 3

Convert current built-in features into capabilities.

Tasks:

- `ToolAgent` logic becomes `ToolCapability`
- `SandboxAgent` lifecycle becomes `SandboxCapability`
- skill logic becomes `SkillCapability`

### Phase 4

Keep wrappers, then simplify internals.

Tasks:

- make `ReactAgent` a thin preset
- make `SandboxAgent` a thin preset
- deprecate direct inheritance-based feature stacking

## Risks and Tradeoffs

### Tradeoff 1

This design introduces more classes.

That is acceptable because the goal is not fewer files. The goal is cleaner ownership boundaries.

### Tradeoff 2

Hook-based capability APIs can become too broad.

Mitigation:

- keep the base hook set small
- only add hooks after a real concrete need appears
- avoid putting loop-specific logic into capabilities

### Tradeoff 3

Composition can become opaque if capability ordering matters too much.

Mitigation:

- document ordering rules
- keep precedence simple
- reserve tool execution ownership for `ToolCapability`

## Final Recommendation

Adopt the following architectural rule:

> Agent behavior styles are defined by `BaseLoop` subclasses.
> Optional features are defined by `BaseCapability` subclasses.
> Final runtime behavior is assembled by one concrete `Agent`.

This keeps the preferred abstraction-first, inheritance-heavy design style, while fixing the current problem that capability combinations are trapped in subclass hierarchy.

In practical terms, the target model should be:

- `BaseAgent` for orchestration
- `BaseLoop` for execution strategy
- `BaseCapability` for optional features
- `AgentSession` for all mutable run state
- thin preset agents for convenience

That gives the project a stable foundation for:

- sandbox + tools without skills
- tools without sandbox
- custom loops with the same capabilities
- future approvals, tracing, streaming, or planning support

without continuing to grow the inheritance chain.
