# Current Architecture Discussion Notes

## Purpose

This document summarizes the current architecture problems in EasyAgent and the candidate redesign directions we have discussed.

It is not a final design spec.
It is a discussion memo intended to help review the tradeoffs before implementation.

## Current Problems

### 1. Agent capabilities are coupled through inheritance

The current structure is roughly:

- `BaseAgent`
- `ToolAgent(BaseAgent)`
- `ReactAgent(ToolAgent)`
- `SandboxAgent(ReactAgent)`

This creates a fixed capability chain.
It works for the default path, but becomes awkward when feature combinations diverge.

Examples:

- need sandbox + tools, but no skills
- need tools, but not ReAct
- need custom runtime behavior without inheriting unrelated features

The core issue is that capability combinations are encoded in the class hierarchy.

### 2. Memory currently mixes storage and context-building

Current memory abstractions do two different jobs at once:

- store interaction history
- decide what subset of history is sent to the model

Example:

- `SlidingWindowMemory.add()` stores data
- `SlidingWindowMemory.get_messages()` returns a truncated view

This means `Memory` is acting as both:

- a historical record
- a context selection strategy

That is conceptually mixed.

### 3. SummaryMemory is irreversible

`SummaryMemory` summarizes older messages during the memory update path.
That means raw history is replaced by compressed history.

This creates several problems:

- original records are lost
- debugging becomes harder
- replay becomes weaker
- interrupt / resume becomes less reliable
- summary logic is forced into the storage layer

### 4. Session state is not clearly separated from agent configuration

At the moment, several runtime concerns are effectively attached to the agent implementation itself:

- message history
- enabled tools
- active skill loading path
- sandbox context

This makes it harder to support:

- multiple sessions from the same agent
- dynamic runtime changes
- future interrupt / resume
- model switching within one session

### 5. Tool and skill ownership is ambiguous

There is not yet a clean distinction between:

- what tools and skills an agent knows about in principle
- what tools and skills are active in one specific run

This becomes more important if a session can switch models during execution.

### 6. Sandbox and tools are currently too tightly coupled

The current `SandboxAgent` bundles together:

- sandbox lifecycle
- sandbox-backed tool exposure

This makes the architecture less orthogonal than it should be.

Ideally:

- sandbox should provide a runtime resource
- tools should expose callable operations

Those are related, but not the same concern.

### 7. Capability hooks may grow too quickly

The proposed `BaseCapability` direction is useful, but there is a risk that it becomes a large hook bag if not constrained.

Without discipline, every new feature may add one more hook into the base interface.

## Main Design Direction Discussed

We discussed moving from inheritance-stacked feature agents toward:

- `BaseAgent` for orchestration
- `BaseLoop` for execution strategy
- `BaseCapability` for optional runtime features
- `AgentSession` for all mutable run state
- separate `Memory` and `Context` abstractions

The key idea is:

> execution style is a loop concern  
> optional features are capability concerns  
> mutable state is a session concern

## Proposed Core Abstractions

### BaseAgent

Role:

- owns static configuration
- owns registries and default capabilities
- creates and manages sessions
- delegates runtime progression to the loop

### BaseLoop

Role:

- controls progression of one run
- decides when to call the model
- decides when to execute tools
- decides when to finish

Examples:

- `ReActLoop`
- `SingleTurnLoop`
- future `PlanActLoop`

### BaseCapability

Role:

- contributes optional runtime behavior
- may expose tools, resources, prompts, or lifecycle behavior
- should not own the main loop

Examples:

- `ToolCapability`
- `SandboxCapability`
- `SkillCapability`
- future trace or approval capability

### AgentSession

Role:

- stores all mutable run-level state
- isolates one session from another
- makes interrupt / resume / model switching easier

Candidate responsibilities:

- current model
- memory
- context
- enabled tools
- loaded skills
- resources
- metadata
- status

## Strongest Design Decision So Far

### AgentSession should own mutable runtime state

This was the clearest and most important conclusion.

The session should carry run-specific state instead of storing it on the agent instance.

Why this matters:

- supports future interrupt / resume
- supports multiple sessions from one agent
- avoids runtime state leaking across sessions
- supports per-session tool activation
- supports per-session model switching

## Memory vs Context Separation

This became the most important architectural refinement after the initial loop/capability split.

### Problem with current design

Current memory abstractions mix:

- recording full history
- preparing the subset sent to the model

That is two different responsibilities.

### Proposed semantic split

#### Memory

Memory should be a faithful recorder.

Responsibilities:

- store all interaction history
- return complete history
- avoid truncation, summarization, or model-specific shaping

Candidate abstraction:

```python
class BaseMemory(ABC):
    @abstractmethod
    def add(self, message: Message) -> None: ...

    @abstractmethod
    def get_all(self) -> list[Message]: ...

    @abstractmethod
    def clear(self) -> None: ...
```

Candidate implementations:

- `InMemoryMemory`
- future `FileMemory`
- future `SQLiteMemory`

#### Context

Context should build model input from memory.

Responsibilities:

- select what part of history is sent to the model
- inject system prompt
- apply sliding window strategy
- apply summary strategy
- later support retrieval or hybrid context selection

Candidate abstraction:

```python
class BaseContext(ABC):
    @abstractmethod
    def build_messages(
        self,
        memory: BaseMemory,
        system_prompt: str,
    ) -> list[dict[str, Any]]: ...
```

Candidate implementations:

- `FullContext`
- `SlidingWindowContext`
- `SummaryContext`

### Important conclusion

Summary should belong to `Context`, not to `Memory`.

That means:

- summary can be cached by the context strategy
- memory remains complete and lossless
- debugging and replay stay reliable

### Example SummaryContext idea

`SummaryContext` may keep internal cache such as:

- cached summary text
- count of messages already summarized

This state belongs to the context object for the session.
It should not overwrite raw memory history.

## Session Design Direction

A candidate shape discussed was:

```python
class AgentSession:
    current_model: BaseLLM
    memory: BaseMemory
    context: BaseContext
    enabled_tools: list[str]
    loaded_skills: list[str]
    resources: dict[str, Any]
    metadata: dict[str, Any]
    status: AgentStatus
    final_output: str | None
    iteration_count: int

    def add_message(self, msg: Message) -> None:
        self.memory.add(msg)

    def get_model_messages(self, system_prompt: str) -> list[dict]:
        return self.context.build_messages(self.memory, system_prompt)
```

### Notes

- `resources` means runtime resources such as sandbox instances
- this avoids overloading the word `context`
- `context` in this design means model-input-building strategy, not a generic state dictionary

## Tool and Skill Ownership

We discussed a key distinction:

> definitions belong to the agent  
> activations belong to the session

### Tool design

#### Agent-owned

- tool registry
- default allowed tool set

#### Session-owned

- currently enabled tools

This allows:

- one agent to know many tools
- one session to enable only a subset
- skill loading to expand enabled tools dynamically without mutating global agent state

### Skill design

#### Agent-owned

- skill registry
- known skill definitions

#### Session-owned

- loaded skills
- skill-triggered runtime activation effects

This avoids session-to-session leakage.

## Model Switching Discussion

One important point raised was:

> one session should be allowed to switch models

This means the current model should live in the session, not only on the agent.

Candidate field:

```python
session.current_model: BaseLLM
```

Then loop execution would use:

- `session.current_model` for model calls
- not only `agent.default_model`

This keeps model choice aligned with other run-level state such as enabled tools and loaded skills.

## Capability Composition Direction

We discussed replacing feature-stacked agents with capabilities that can be assembled.

Examples:

### ReAct + tools

```python
Agent(
    model=model,
    loop=ReActLoop(),
    capabilities=[
        ToolCapability(...),
    ],
)
```

### ReAct + sandbox + tools, no skills

```python
Agent(
    model=model,
    loop=ReActLoop(),
    capabilities=[
        SandboxCapability(...),
        ToolCapability(...),
    ],
)
```

### ReAct + sandbox + tools + skills

```python
Agent(
    model=model,
    loop=ReActLoop(),
    capabilities=[
        SandboxCapability(...),
        ToolCapability(...),
        SkillCapability(...),
    ],
)
```

This is much cleaner than encoding those combinations in subclasses.

## Sandbox and Tool Separation

One important conclusion was:

### SandboxCapability should provide a resource, not tools

Responsibilities:

- start sandbox on session enter
- stop sandbox on session exit
- put sandbox instance into `session.resources`

### ToolCapability should expose and execute tools

Responsibilities:

- advertise schemas for enabled tools
- dispatch tool calls
- resolve tools from the registry

Tool implementations that need sandbox should read it from session resources.

This gives a clean separation:

- sandbox = runtime resource
- tool = callable operation

## Tool Dispatch Direction

We discussed using a centralized dispatch chain:

- loop sees tool call
- loop delegates to `agent.execute_tool_call(...)`
- agent asks capabilities in order
- first capability that returns non-`None` handles the call

This is the "first non-None wins" model.

Why it is attractive:

- keeps loop subclasses simple
- centralizes dispatch
- avoids capability logic leaking into loops

## Capability Hook Discipline

A concern was raised that `BaseCapability` may gain too many hooks.

Suggested rule:

> a new hook should only be added to `BaseCapability` if at least two different capability implementations genuinely need it

Otherwise:

- keep the logic local to one capability
- avoid turning `BaseCapability` into a large event bus

## No Backward Compatibility Constraint

An important project constraint was clarified:

- this project is currently for personal use
- older versions are already backed up
- compatibility with previous APIs is not required

This changes the design approach significantly.

Implications:

- old abstractions can be removed instead of wrapped
- misnamed classes should be renamed instead of preserved
- old feature-stacked agent structure does not need compatibility shims

In particular, we discussed that these old roles may be removed or retired rather than preserved:

- `SlidingWindowMemory`
- `SummaryMemory`
- `ToolAgent`
- `SandboxAgent` as a core architectural concept
- ContextVar-style active agent / active sandbox patterns

## Current Best-Guess New Core Set

At this point, the likely new core abstractions look like this:

- `BaseAgent`
- `BaseLoop`
- `BaseCapability`
- `BaseMemory`
- `BaseContext`
- `AgentSession`

First concrete implementations likely include:

- `Agent`
- `ReActLoop`
- `InMemoryMemory`
- `FullContext`
- `SlidingWindowContext`
- `SummaryContext`
- `ToolCapability`
- `SandboxCapability`
- `SkillCapability`

## Current Resolutions

### 1. BaseContext should build only messages

Decision:

- `BaseContext` builds only model-facing messages
- tool schemas are assembled separately by loop/agent at call time

Reason:

- message history and tool schemas have different lifecycles
- skill loading may change `session.enabled_tools` between model calls
- keeping tools outside context keeps responsibilities cleaner

Recommended call path:

```python
messages = session.get_model_messages(system_prompt)
tool_schemas = agent.get_tool_schemas(session)
response = await session.current_model.call(messages, tools=tool_schemas)
```

### 2. Memory should store Message for now

Decision:

- memory stores `Message`
- do not introduce full event-log memory yet
- leave room to extend `Message` with fields such as `semantic_type`

Reason:

- this keeps the redesign moving
- it is enough for current summary and context strategies
- full event-log memory can be introduced later if interrupt/replay requirements become stronger

Current direction:

- start simple with `Message`
- keep future extension path open

### 3. Session should own current_model

Decision:

- `Agent` owns `default_model`
- `AgentSession` initializes `current_model` from `agent.default_model`
- loops always call `session.current_model`
- model switching happens by directly assigning a new model to `session.current_model`

Reason:

- this is almost zero-cost to implement
- it cleanly supports future model switching
- it keeps run-level state inside the session where it belongs

### 4. SkillCapability should handle load_skill directly

Decision:

- `SkillCapability.handle_tool_call("load_skill", ...)` reads the skill body
- it appends declared tools to `session.enabled_tools`
- it returns the skill body string directly
- `ToolCapability` does not need to know skills exist

Reason:

- skill loading is skill logic, not generic tool logic
- this keeps tool execution and skill activation decoupled
- the old ContextVar-style active-agent mechanism is no longer needed

### 5. SummaryContext should receive its own summary model explicitly

Decision:

- `SummaryContext` should accept its own summary model in the constructor

Candidate shape:

```python
SummaryContext(summary_model: BaseLLM, reserve_recent: int = 10)
```

Reason:

- summary generation belongs to the context strategy
- it should not depend on global application config
- the summary model may be different from the session's main model
- it is often desirable to use a cheaper model for summarization

## Open Questions Still Worth Discussing

### 1. Should Message gain semantic_type now or later?

Current leaning:

- not required for the first pass
- but worth leaving room for it soon

Reason:

- it may help `SummaryContext` distinguish thought / observation / final answer
- but it should not block the main refactor

### 2. Should memory later evolve from Message storage to event-log storage?

Current leaning:

- yes, possibly later
- not part of the first architecture cut

Reason:

- event logs would improve replay, checkpoints, and richer debugging
- but they add complexity before the current redesign is settled

## Summary

The strongest conclusions from the discussion so far are:

1. Mutable runtime state should move into `AgentSession`.
2. `Memory` and `Context` should be split cleanly.
3. `Memory` should be complete and lossless.
4. `Context` should be a derived model-input view.
5. Tools and skills should be split into:
   definitions on the agent, activations on the session.
6. Sandbox should be a resource capability, not a bundled agent type.
7. Capability composition is a better fit than feature-stacked agent inheritance.
8. Since compatibility is not required, the redesign can be clean instead of incremental.

## Suggested Next Step

Before implementation, the remaining useful discussion topic is:

- whether this conceptual split is agreed upon strongly enough to turn into the final architecture spec

If yes, the next document should be a stricter design spec containing:

- exact base class APIs
- session lifecycle
- capability ordering rules
- loop-to-capability interaction contract
- memory/context interaction contract
