# Changelog

All notable changes to EasyAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-04-29

The multi-agent layer is rebuilt from scratch around three orthogonal protocols — **Entity** (who acts), **World** (what they perceive), **Schedule** (who goes when) — replacing the previous Talker/Orchestrator/Runtime architecture. The single-agent layer is unchanged.

### Added

**Core protocols (`easyagent/core/`)**
- `Entity` Protocol — `id` property + `async act(Perception) -> Action | None`.
- `World` Protocol — `observe(entity_id) -> Perception`, `apply(entity_id, Action)`, `seed(content, sender)`.
- `Schedule` Protocol — `next(LoopState) -> list[str] | None`.
- `Runtime` — the perceive-act-apply loop wiring Entity + World + Schedule + optional EventBus.
- `RuntimeResult` — with `actions`, `ticks`, `last_speech`, `speeches` helpers.

**Perception & Action types (`easyagent/core/types.py`)**
- `Perception` — immutable bag of typed `PerceptionSlice`s with `of_type()` / `all_of_type()` helpers.
- `PerceptionSlice` variants: `MessagesSlice`, `SpatialSlice`, `StateSlice`.
- `Action` hierarchy: `Speak`, `Move`, `SetState`, `Silent`, `Composite` — all frozen dataclasses.
- `ChatMessage` — lightweight `sender`, `content`, `to`, `channel` for multi-agent messaging.
- `LoopState` — mutable tick counter + action log for Schedule decisions.

**Schedule implementations (`easyagent/core/schedule.py`)**
- `TakeTurns` — fixed sequence, returns None after last.
- `RoundRobin` — one per tick, cycling.
- `AllParallel` — everyone acts each tick.
- `RandomOrder` — one per tick, random.
- `Reactive` — addressed entity speaks next (reads action_log).
- `MaxTicks(inner, n)` — caps at N ticks.
- `UntilIdle(inner, grace)` — stops after N silent ticks.
- `UntilPredicate(inner, predicate)` — stops on predicate.

**World implementations (`easyagent/worlds/`)**
- `ConversationWorld` — flat chat history, broadcast visibility.
- `PipelineWorld(order)` — entity N sees only seed + entity N-1's output.
- `SpatialWorld` + `Grid2D` — 2D grid with range-limited perception (`SpatialSlice`).
- `StatefulWorld(inner)` — decorator adding `StateSlice` + `SetState` handling to any World.
- `SharedState` — versioned KV blackboard with subscriptions and `async wait_for`.

**Entity implementations (`easyagent/entities/`)**
- `LLMEntity` — wraps an `Agent`; rebuilds memory from Perception each turn (eliminates double-write).
- `TeamEntity` — wraps an inner `Runtime` as a single Entity for recursive nesting.
- `HumanEntity` — reads from `asyncio.Queue` or callback.

**Presets (`easyagent/presets.py`)**
- `sequential(entities, seed)` — PipelineWorld + TakeTurns.
- `fanout(entities, seed)` — ConversationWorld + AllParallel + MaxTicks(1).
- `debate(entities, rounds, seed, judge=)` — ConversationWorld + RoundRobin + MaxTicks, optional judge.
- `chatroom(entities)` — returns `ManualSession` context manager with attribute-based routing.
- `groupchat(entities, rounds, seed)` — ConversationWorld + Reactive + UntilIdle + MaxTicks.

**Context**
- `MultiAgentFormatter` migrated to `easyagent/context/multi_agent.py` — folds non-self messages into `<history>` block for LLM prompts.

**Tests**
- `easyagent/test/test_core.py` — 33 tests covering all Schedule, World, and Runtime behaviour.

**Examples rewritten (07–14)**
- `07_two_agents_talk` — LLMEntity + ConversationWorld + RoundRobin.
- `08_sequential` — sequential() preset.
- `09_chatroom` — ManualSession with manual routing.
- `10_groupchat` — Reactive schedule, LLM picks next.
- `11_debate_and_judge` — debate() with third-party judge.
- `12_nested` — TeamEntity: Runtime-as-Entity nesting.
- `13_shared_state` — SharedState + StatefulWorld + UntilPredicate.
- `14_advanced_runtime` — SpatialWorld: 2D grid + Move + Composite actions.

### Changed

- Top-level `easyagent` package surface updated: exports Entity, World, Schedule, Runtime, all perception/action types, all entity/world/schedule implementations, all presets.
- `pyproject.toml` description updated for new architecture.
- `README.md` / `README_CN.md` rewritten around Entity-World-Schedule.
- `docs/architecture.md` rewritten for the new three-protocol design.

### Removed

- `easyagent/chat/` — entire directory (Orchestrator, Talker, LLMTalker, HumanTalker, RuntimeTalker, ChatMessage/Identity, strategies/routing, strategies/stop, strategies/summarize, strategies/turn_taking, presets, turn_context, formatter, shared_state).
- `easyagent/runtime/` — entire directory (BaseRuntime, TickBasedRuntime, policies, state).

---

## [0.3.0] - 2026-04-28

The biggest release since the SDK started. The runtime is rebuilt around three layers — a single-agent ladder (`Agent` → `ReactAgent` → `SkillAgent` / `SandboxAgent`), a tick-driven runtime layer for autonomous group simulation, and a **chat layer** that is the new default entry point for multi-agent collaboration.

### Added

**Single-agent layer**
- `BaseAgent` / `Agent` (single-turn) / `ReactAgent` (ReAct loop) / `SkillAgent` / `SandboxAgent` — clean inheritance chain, with loop logic now living in `agent.step()`.
- `AgentSession` — the per-execution instance (renamed from `AgentRuntime`). New `on_events(events) -> list[BaseEvent]` hook for multi-agent participation; default delivers the last incoming `MessageEvent` and replies preserving visibility (broadcast-on-broadcast, DM-back-to-sender).
- `BaseAgent.observe(msg, *, session=None, sender=None)` — read-only memory absorption surfaced at the agent level so a plain `BaseAgent` can play the "watch the conversation" role without the chat-layer wrapper.
- `SkillAgent` — auto-registers `load_skill` / `list_skill_files` / `read_skill_file` / `run_skill_script` so the model can discover and load `SKILL.md` packages on demand.
- `SandboxAgent` — auto-registers `bash` / `write_file` / `read_file` and manages sandbox lifecycle via `on_session_start` / `on_session_end`.
- `Message.name` — optional sender name, used by the chat layer's multi-agent formatter to disambiguate self vs. others in shared memory.
- `Message.to_api_dict()` — excludes `reasoning_content` by default; provider-specific replay can opt in with `include_reasoning=True`.

**Tools**
- `EndTool` — the canonical "I'm done" tool. `ReactAgent` installs it by default (`auto_end=True`); calling `end(data=...)` stops the loop and publishes `StopEvent` for observability.
- `ThinkTool` — side-effect-free scratch pad. The `thought` argument lands in tool-call history so the model can re-read its own reasoning. Installed in `ReactAgent` by default (`auto_think=True`).
- `ToolManager` / `SkillManager` are now normal registries instead of constructor-level singletons. `register_tool` / `register_skill` target process default registries; agents can receive explicit managers for isolation.

**Events and runtime (`easyagent.events`, `easyagent.runtime`)**
- `BaseEvent`, `EventBus`, plus telemetry events (`LLMCalledEvent`, `ToolCalledEvent`, `ToolResultEvent`, `StopEvent`).
- `MessageEvent` — the only communication primitive. Visibility (`to="*"` broadcast, `to=frozenset(...)` DM/subgroup) is a property of the message, not a channel object.
- `WaitEvent` — an agent returns this to skip the current tick and be re-delivered next round.
- `BaseRuntime` — minimal abstract base: holds agents, bus, state. Stable `name` property used by `RuntimeTalker`.
- `TickBasedRuntime` — tick loop with `StepPolicy` / `SchedulePolicy` / `StopPolicy`, `WaitEvent` handling, and `on_undeliverable` hook for human-in-the-loop. Each tick boundary and the chosen execution order are logged at INFO level.
- Presets: `ParallelRuntime` / `SequentialRuntime` / `ShuffledRuntime` (TickBasedRuntime with `schedule_policy` pre-filled).
- Policies: `DeliverToRecipients`, `TickDriven` (StepPolicy); `Parallel`, `Sequential`, `Shuffled` (SchedulePolicy); `StopWhenIdle`, `StopAfterTicks`, `StopAfterEvents`, `StopWhenMessageMatches`, `AnyOf` (StopPolicy).
- `BaseRuntime` injects `tick` / `max_ticks` into `AgentSession.metadata` so agents can sense time pressure.

**Chat layer (`easyagent.chat`) — recommended starting point for multi-agent**
- `ChatMessage` / `Identity` — user-facing conversation primitives. Routing (`to`, `channel`) lives on the message itself.
- `Talker` protocol with three adapters: `LLMTalker` (wraps any `BaseAgent`), `HumanTalker` (queue/UI input), `RuntimeTalker` (wraps any `BaseRuntime`).
- `Orchestrator` — multi-Talker container. Itself implements `Talker`, so containers nest natively.
- Strategies along four axes, each pluggable, with built-ins:
  - **Routing**: `Broadcast`, `Direct`, `Pipeline`.
  - **TurnTaking**: `Conducted`, `Reactive`, `RoundRobin`, `Random`, `Weighted`, `Selected`, `Manual`.
  - **StopCondition**: `MaxRounds`, `Idle`, `AfterAllSpoken`, `OnPredicate`, `OnSharedKey`, `AnyOf`, `AllOf`.
  - **Summarize**: `LastMessage`, `Aggregate`, `ByJudge`, `FromSharedState`, `Custom`.
- Presets: `sequential`, `fanout`, `chatroom`, `groupchat`, `debate`.
- `MultiAgentFormatter` — renders multi-speaker memory into a per-Talker prompt with `<history>` folding so an agent never mistakes others' words for its own. Auto-installed by `LLMTalker`; degrades to standard formatting for single-agent flows.
- `SharedState` — versioned KV blackboard with subscriptions, async `wait_for`, and a bus bridge (`StateChangedEvent`).

**Examples (single-concept-per-step ladder, 00–14)**
- `00`–`06` single-agent: `model_call`, `single_turn_agent`, `memory_and_context`, `react_with_tools`, `skills_lazy_loading`, `sandbox_agent`, `custom_tool`.
- `07`–`13` chat layer: `two_agents_talk`, `sequential`, `chatroom`, `groupchat`, `debate_and_judge`, `nested`, `shared_state`.
- `14_advanced_runtime` — tick-based simulation with custom session and policies.

**Docs**
- New `docs/architecture.md` — single architecture overview replacing the scattered prior design notes.
- `README.md` / `README_CN.md` rewritten around the new layers (single-agent → chat → runtime) and the renumbered example ladder.

### Changed

- `AgentRuntime` → `AgentSession`; `create_runtime()` → `create_session()`.
- `ReactAgent` is the canonical ReAct loop agent (consolidates prompt construction, tool-call formatting, and telemetry emission). `SkillAgent` and `SandboxAgent` now subclass `ReactAgent`.
- A plain-text LLM response (no tool calls, no end token) is treated as a completed answer in the ReAct loop instead of "continue" — fixes infinite loops in group-chat scenarios.
- Top-level `easyagent` package surface is intentionally smaller: `Agent` / `ReactAgent` / `SkillAgent` / `SandboxAgent` / `AgentSession` / `AgentRunResult` / `LiteLLMModel` / `Message` / `MessageEvent` / `EventBus` / `ToolManager` / `SkillManager` / `register_tool`. Submodule access for everything else.

### Removed

- `easyagent/loop/` (`SingleTurnLoop`, `ReActLoop`) — loop logic now lives in `agent.step()`.
- `easyagent/capability/` (`ToolCapability`, `SkillCapability`, `SandboxCapability`) — replaced by dedicated `ReactAgent` / `SkillAgent` / `SandboxAgent` subclasses.
- `easyagent/pipeline/` (`Team`, `BaseNode`, `BasePipeline`) — superseded by `chat.sequential` for static pipelines and `Orchestrator(turn_taking=Conducted)` for custom containers.
- Stale design docs under `docs/` (`agent-capability-architecture.md`, `agent-system-design-new.md`, `current-architecture-discussion-notes.md`).
- Old examples (`simple_react_agent.py`, `session_agent_demo.py`, `tool_skill_sandbox_demo.py`) — superseded by the 00–14 ladder.

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
