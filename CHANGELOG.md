# Changelog

All notable changes to EasyAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-04-25

Complete redesign of the multi-agent layer. The previous `Supervisor`, `Session`,
and `Team` APIs have been replaced by a single unified set of primitives.

### Added

**Communication primitives**
- `MessageEvent` — the only communication primitive. Visibility (`to="*"` broadcast, `to=frozenset(...)` DM/subgroup) is a property of the message, not a channel object.
- `WaitEvent` — an agent returns this to skip the current tick and be re-delivered next round.
- `EventBus` — unchanged, but now the single source of truth for all events across the system.

**Runtime abstractions**
- `BaseRuntime` — minimal abstract base: holds agents, bus, state. `run()` is abstract. No tick logic, no policies.
- `TickBasedRuntime` — intermediate layer adding tick loop, `StepPolicy` / `SchedulePolicy` / `StopPolicy`, `WaitEvent` handling, and `on_undeliverable` hook for human-in-the-loop.
- `ParallelRuntime` / `SequentialRuntime` / `ShuffledRuntime` — `TickBasedRuntime` presets that pre-fill `schedule_policy`.
- `PipelineRuntime` — fixed linear hand-off chain (no tick loop). Non-terminal agents auto-receive a pipeline-aware `end` tool.

**Policies**
- `DeliverToRecipients` — routes `MessageEvent` by `to` field; non-message events go to all sessions.
- `TickDriven` — ignores event stream, sends a tick signal to all sessions each round.
- `Parallel` / `Sequential` / `Shuffled` — `SchedulePolicy` implementations controlling per-tick execution order.
- `StopWhenIdle` — halts when no new events are produced.
- `StopAfterTicks` — halts after N ticks (1-based counting).
- `StopAfterEvents` — total event budget.
- `StopWhenMessageMatches` — user-defined predicate on `MessageEvent`.
- `AnyOf` — compose multiple stop policies.

**Agent**
- Loop logic moved into agent `step()` methods. `Agent.step()` is single-turn; `ReactAgent.step()` is one ReAct iteration (LLM call + tool execution).
- New agent inheritance chain: `Agent` (single-turn) → `ReactAgent` (ReAct loop with tools) → `SkillAgent` / `SandboxAgent`.
- `AgentSession.on_events(events: list[BaseEvent]) → list[BaseEvent]` — new hook for multi-agent participation. Default delivers the last incoming `MessageEvent` to the loop and replies preserving visibility (broadcast-on-broadcast, DM-back-to-sender). Subclasses override to customize routing, `@xxx` parsing, etc.
- `SharedStore` — optional versioned KV store for sharing artifacts between agents.

**Tick awareness**
- `BaseRuntime._call_agent` injects `tick` and `max_ticks` into `AgentSession.metadata` before each `on_events` call, so agents can sense time pressure.
- `StopAfterTicks` writes its limit into `RuntimeState.max_ticks` so policies and agents can read it.
- `TickBasedRuntime` logs each tick boundary and the schedule policy's chosen execution order at INFO level for clearer multi-agent traces.

### Changed

- `AgentRuntime` has been renamed to `AgentSession`; `create_runtime()` is now `create_session()`.
- `ToolManager` and `SkillManager` are normal registries instead of constructor-level singletons. `register_tool` / `register_skill` target process default registries, while agents can receive explicit managers for isolation.
- `ReactAgent` is the canonical ReAct loop agent (consolidating prompt construction, tool-call formatting, and telemetry emission). `SkillAgent` and `SandboxAgent` now subclass `ReactAgent`.
- `Message.to_api_dict()` excludes `reasoning_content` by default. Provider-specific replay can opt in with `include_reasoning=True`.
- A plain text LLM response (no tool calls, no end token) is now treated as a completed answer in the ReAct loop instead of `continue`. This fixes infinite loops in group-chat scenarios.
- `RuntimeState.tick` now starts at 1 (incremented at the top of the loop, before execution).
- `StopAfterTicks` uses `>` instead of `>=` so `max_ticks=5` means "run 5 full ticks".

### Removed

- `easyagent/supervisor/` — replaced by coordinator agent pattern in user space.
- `easyagent/session/` — replaced by `Runtime` + `EventBus`.
- `easyagent/loop/` — `SingleTurnLoop` / `ReActLoop` are gone; loop logic is now part of the agent's `step()` method.
- `easyagent/capability/` — `ToolCalling` / `Skills` / `Sandbox` capabilities replaced by dedicated `ReactAgent` / `SkillAgent` / `SandboxAgent` subclasses.
- `easyagent/pipeline/` (`Team`, `BaseNode`, `BasePipeline`) — replaced by `PipelineRuntime` in `easyagent/runtime/pipeline.py`.
- `SessionEvent` base class — all events now inherit directly from `BaseEvent`.
- `CommunicationEvent` alias — use `MessageEvent` directly.
- `Agent.on(event_type, handler)` — old Session-era event subscription API.
- `ChatAgent` / `ChatDecision` — group-chat behaviour is now expressed by overriding `on_events` on any `AgentSession` subclass.
- All `supervisor_*`, `team_*`, `multi_agent_demo`, `session_agent_demo` examples.
- Leaked `20260424_*_supervisor_task/` runtime artefact directories.

### Fixed

- `.gitignore` now covers timestamped runtime artefact directories (`/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_*/`).

---

## [0.2.0] - 2026-01-20

### Changed

- Rebuilt the core runtime around `AgentSession`, `BaseLoop`, `BaseMemory`, and `BaseContext`.
- Split memory storage from model-facing context assembly.
- Replaced feature-stacked agent internals with capability composition.
- Reworked `ReactAgent` and `SandboxAgent` into thin presets.
- Added `InMemoryMemory`, `FullContext`, `SlidingWindowContext`, `SummaryContext`.
- Added `ToolCapability`, `SkillCapability`, `SandboxCapability`.

### Fixed

- Synchronized top-level exports with the actual runtime architecture.

---

## [0.1.4] - 2026-01-15

### Added

- `Message.reasoning_content` field for storing LLM thinking content.
- `Message.from_response()` class method.
- `Message.to_api_dict()` method.

---

## [0.1.3] - 2026-01-10

### Added

- Auto-discover tools feature.
- Tests for tool discovery.

---

## [0.1.2] - Earlier releases

See git history for earlier changes.
