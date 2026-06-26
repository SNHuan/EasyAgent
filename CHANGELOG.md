# Changelog

All notable changes to EasyAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.7] - 2026-06-26

EasyAgent 0.6.7 extends the local dashboard trace tree with custom grouping
paths for external and custom trace producers. Runs can now be projected as
`run -> custom groups -> entity -> session` without changing the trace store
schema.

### Added

- `dashboard_group_path` trace metadata for dashboard-specific hierarchy
  projection.
- Dashboard API `runs[].tree` output that merges sessions by custom group path
  and then attaches the existing entity/session leaves.
- Recursive dashboard trace tree rendering with fallback to the previous
  entity/session tree when no custom grouping metadata is present.
- `ExternalAgentEntity` promotion of
  `ExternalResult.metadata["dashboard_group_path"]` into session trace metadata.
- `examples/18_dashboard_custom_groups.py` showing a fake external runner that
  writes grouped dashboard traces.

### Changed

- Dashboard frontend code is split into route and shell modules while keeping
  the bundled static dashboard assets in sync.

### Install

```bash
pip install -U easy-agent-sdk==0.6.7
```

## [0.6.6] - 2026-06-20

EasyAgent 0.6.6 tightens multi-agent runtime semantics and improves MCP tool
result normalization. Runtime ticks now use a clearer observe/act/apply split,
and MCP integrations preserve structured provider results more reliably.

### Changed

- Runtime tick execution now snapshots all active entity perceptions before
  running entity actions, then applies actions in deterministic active-entity
  order.
- Multi-entity ticks now run the `act()` phase concurrently with
  `asyncio.gather()` while keeping the action log deterministic.
- Runtime tick is now synchronized into worlds that expose `set_tick()`, making
  `Perception.tick` follow the runtime tick source of truth.
- Worlds may now expose `advance(tick)` for optional per-tick world dynamics;
  `StatefulWorld` forwards both `set_tick()` and `advance()` to its inner
  world.
- MCP result normalization now prefers `structuredContent` /
  `structured_content` over less precise `data` payloads.
- MCP structured values are converted through a JSON-safe normalizer before
  serialization, including pydantic-style `model_dump()`, legacy `dict()`,
  `root`, bytes, mappings, and iterables.

### Fixed

- Avoided MCP result output falling back to opaque root-like object strings
  when a structured content payload is available.
- Preserved plain content output ahead of fallback `data` when MCP providers
  return both.

### Install

```bash
pip install -U easy-agent-sdk==0.6.6
```

## [0.6.5] - 2026-06-10

EasyAgent 0.6.5 adds first-class wrappers for externally managed coding
agents. Claude Code SDK and Codex SDK can now be registered as runtime
entities, traced through the existing event system, and inspected in the local
dashboard.

### Added

- `easyagent.external` with `ExternalAgentEntity`, `ExternalResult`,
  `ExternalRunner`, `ClaudeCodeRunner`, `CodexRunner`, `claude_code_entity`,
  and `codex_entity`.
- Optional dependency groups: `external`, `claude`, and `codex` for installing
  Claude Code SDK and Codex SDK integrations only when needed.
- Real external agent examples:
  - `examples/16_external_claude_code.py`
  - `examples/17_external_codex.py`
- `.env.example` as the single local environment example for EasyAgent core,
  Serper, Claude Code SDK, and Codex/OpenAI SDK configuration.
- `register_token_usage_adapter()` for provider-specific token usage
  normalization.

### Changed

- Runtime tracing now supports external agent provider events, including
  messages, streaming deltas, tool calls, tool results, final results, failures,
  and provider session ids.
- The dashboard Messages view now renders external agent transcripts with
  user prompts on the right and agent process/final messages on the left.
- Claude Code and Codex tool results are summarized by default; long result
  payloads stay collapsed until expanded in the dashboard.
- Token usage normalization now understands OpenAI/Codex-style
  `input_tokens` / `output_tokens` payloads and Claude cache token details.
- README and README_CN now reference the unified `.env.example` and include the
  updated dashboard screenshot.

### Removed

- Removed the older `.example_env` file to avoid ambiguity with
  `.env.example`.

### Install

```bash
pip install -U easy-agent-sdk==0.6.5
```

## [0.6.4] - 2026-05-29

EasyAgent 0.6.4 adds a small display protocol for custom trace events. SDK
users can now persist user-defined events and tell the dashboard how to project
those events into supported UI surfaces such as Messages and Timeline.

### Added

- `CustomTraceEvent` for user-defined trace events with explicit persisted
  event types, arbitrary JSON-friendly payloads, and optional dashboard display
  metadata.
- `DisplayHint` helper for attaching dashboard rendering metadata to custom
  trace events without requiring a trace store schema migration.
- Dashboard support for `payload.display.surface == "messages"`, rendering
  custom events in the Messages tab as chat bubbles.
- Dashboard support for custom event `display.title` / `display.content`
  timeline summaries and `display.surface == "hidden"` timeline hiding.
- README and README_CN examples showing how to publish a custom event that
  appears in the dashboard Messages view.

### Changed

- `TraceRecorder` now preserves a `CustomTraceEvent.event_type` value as the
  persisted trace event type and merges its custom payload into the stored
  event payload.

### Install

```bash
pip install -U easy-agent-sdk==0.6.4
```

## [0.6.3] - 2026-05-29

EasyAgent 0.6.3 tightens the runtime observability dashboard introduced in
0.6.2. The dashboard now keeps runtime navigation state intact, renders runtime
and session timelines more reliably, and improves token usage inspection.

### Added

- Runtime detail views now include a runtime timeline that mixes runtime events
  and child session entries in timestamp order.
- Runtime timeline event selection now drives the Event Payload inspector so
  runtime event payloads can be inspected directly.

### Changed

- Runtime and session timeline connector lines are now drawn at the timeline
  container level instead of per row, avoiding broken or misaligned connectors
  when zoom level or row height changes.
- Returning from a session opened from the runtime timeline now restores the
  runtime timeline tab instead of resetting to the runtime overview.
- Token Usage bar chart tooltips now align to the chart edge for the first and
  last bars so they are not clipped.
- README dashboard guidance no longer points to removed example scripts.

### Install

```bash
pip install -U easy-agent-sdk==0.6.3
```

## [0.6.2] - 2026-05-29

EasyAgent 0.6.2 adds runtime-level observability on top of the existing agent
session tracing. Runtime runs can now be inspected as a hierarchy of runtime,
world, entity, and child agent sessions in the local dashboard.

### Added

- `Runtime` now emits runtime lifecycle, tick, and entity lifecycle events when
  connected to an `EventBus`.
- `LLMEntity` binds child agent sessions to the active runtime trace context so
  model calls, tool events, token usage, and messages are grouped under the
  parent runtime run.
- `TraceRecorder` persists runtime events separately from agent session events
  while keeping both linked by `run_id`.
- Dashboard API responses now expose top-level `runs[]` with `world`,
  `entities`, child `sessions`, runtime events, and aggregated token usage.
- Dashboard session navigation now renders a compact runtime/entity/session
  tree with independent runtime and entity expansion.

### Changed

- The dashboard detail view now supports runtime overview and session timeline
  modes without forcing navigation when expanding an entity in the tree.
- Token and event summaries follow the selected runtime or session scope.
- Event payload inspection can show runtime metadata as well as session event
  payloads.

### Examples

- `examples/16_dashboard_runtime_tree.py` generates deterministic runtime tree
  data for UI verification.
- `examples/17_real_runtime_tracing.py` runs real `gemini-3-flash-preview`
  runtimes and writes trace data to a dashboard-readable SQLite database.

### Install

```bash
pip install -U easy-agent-sdk==0.6.2
```

## [0.6.1] - 2026-05-28

EasyAgent 0.6.1 polishes the local dashboard experience for real streaming
agent runs. The dashboard can now update while an LLM response is still being
generated, keeps stream-heavy timelines readable, and presents token usage with
clear current-session versus all-session scopes.

### Added

- `LLMStreamChunkEvent` trace events are emitted during `Agent.stream()` and
  `ReactAgent.stream()` so live dashboards can render partial assistant output
  before the final `LLMRespondedEvent`.
- The dashboard SSE endpoint now detects SQLite trace changes from table state
  instead of relying on file modification timestamps.
- Token Usage now has `Current` and `All` modes: `Current` shows the selected
  session input/output mix as a donut chart, while `All` shows all sessions as
  an hourly stacked bar chart.

### Changed

- Dashboard message bubbles now use streaming chunk events for in-progress
  assistant output, then reconcile with the final response payload.
- Timeline display collapses consecutive stream chunk events into one grouped
  row while preserving the original event ids in the payload panel.
- Token totals, input tokens, and output tokens now follow the selected Token
  Usage scope instead of always showing the selected session.
- Filter and Trace DB popovers now close on outside click or Escape.
- Event mix and token usage charts now include subtle reveal animations.
- Trace DB selection is intentionally configured at startup via
  `easyagent dashboard --db path/to/traces.db`; the dashboard no longer exposes
  a runtime DB switching control.
- Removed dashboard-only helper scripts from `apps/dashboard/scripts`.

### Install

```bash
pip install -U easy-agent-sdk==0.6.1
```

## [0.6.0] - 2026-05-28

EasyAgent 0.6 turns the SDK into a more inspectable agent framework while
keeping the core package lightweight. Agent runs can now be persisted as
structured traces, inspected in a bundled local dashboard, streamed token by
token, and extended with Agent Skills-compatible skill packages.

### Added

**Tracing and stores**
- `easyagent.tracing` with `TraceRecorder`, `SessionTrace`, `EventTrace`, and
  `TokenUsage` for recording agent sessions.
- `easyagent.store` with `MemoryStore`, `JSONLStore`, and `SQLiteStore`.
- Agent lifecycle, LLM, tool-call, tool-result, finished, and failed events are
  recorded as JSON-friendly trace payloads.
- `examples/15_tracing.py` demonstrates persisting traces to SQLite.

**Dashboard and CLI**
- New `easyagent dashboard` command starts a local observability dashboard.
- The dashboard reads `.easyagent/traces.db` by default and supports
  `--db`, `--host`, `--port`, and `--open`.
- Bundled dashboard UI for session lists, timeline events, message history,
  token usage, event payloads, event mix charts, DB status, and resizable panes.
- Local HTTP API endpoints: `/api/health`, `/api/traces`, and the SSE endpoint
  `/api/traces/stream`.

**Streaming**
- Model adapters can stream `LLMStreamChunk` values.
- `Agent` and `ReactAgent` support streaming model output while still emitting
  normal trace events and token usage when providers return usage metadata.
- Streaming responses now emit `LLMStreamChunkEvent` trace rows so the local
  dashboard can update message bubbles before the final response completes.

**Agent Skills-compatible loading**
- Skills now follow the [Agent Skills](https://agentskills.io/) `SKILL.md`
  directory standard.
- `SKILL.md` requires YAML frontmatter with at least `name` and `description`;
  `name` must match the parent directory.
- Default skill discovery path is `.easyagent/skills`.
- `EA_SKILLS_DIR` can point at compatible skill directories such as
  `.claude/skills` or `.codex/skills`.
- Skill examples moved under `examples/.easyagent/skills`.

**Tests**
- Tests now live in top-level `tests/` instead of the package directory.
- Added tracing store tests for in-memory, JSONL, and SQLite persistence.

### Changed

- ReAct completion no longer depends on dedicated `end` or `think` tools.
  A plain assistant response with no tool calls is treated as the final answer.
- Removed built-in `end` and `think` tools from the default ReAct prompt.
- Top-level exports now include stream chunks, tracing types, and store types.
- README / README_CN document the dashboard command and Agent Skills loading.
- `pyproject.toml` now exposes the `easyagent` console script and includes the
  bundled dashboard static assets in package data.

### Removed

- `easyagent/tool/end.py`
- `easyagent/tool/think.py`
- In-package `easyagent/test/` test tree.

### Install

```bash
pip install -U easy-agent-sdk==0.6.0
```

Open the dashboard:

```bash
easyagent dashboard --db .easyagent/traces.db --open
```

---

## [0.5.1] - 2026-05-28

EasyAgent now supports MCP as an external tool source. Users can point the SDK
at a FastMCP/MCP config, discover remote tools, register them into a
`ToolManager`, and decide per `AgentSession` which tools are visible to the
model.

### Added

**MCP integration (`easyagent/mcp/`)**
- `MCPToolset` — discovers tools from a FastMCP-compatible source and exposes
  them as EasyAgent tools.
- `load_mcp_tools(source, *, servers=None, tags=None)` — returns MCP-backed
  tool adapters without mutating a registry.
- `register_mcp_tools(tool_manager, source, *, servers=None, tags=None)` —
  incrementally registers discovered MCP tools into an existing `ToolManager`
  and returns the registered tool names.
- `MCPToolAdapter` — bridges MCP tool calls into EasyAgent's `Tool` protocol.
- `FastMCPClientAdapter` — wraps `fastmcp.Client` while keeping FastMCP as an
  implementation detail of the MCP module.
- `MCPToolInfo` / `MCPToolResult` plus result normalization helpers for MCP
  text, structured content, resource blocks, and errors.

**Tool selection**
- MCP config server names can be used as natural categories via
  `servers=["literature"]`.
- FastMCP tool tags are preserved from `meta["_fastmcp"]["tags"]` and can be
  filtered with `tags=[...]`.
- MCP tool registration is additive: registering one MCP server does not clear
  existing local or remote tools.

**Examples**
- `examples/mcp/fastmcp_in_memory.py` — in-memory FastMCP server consumed by
  EasyAgent.
- `examples/mcp/config_load.py` — loads `mcp_config.example.json`, registers a
  selected MCP server's tools, and enables them on a session.
- `examples/mcp/mcp_config.example.json` — standard `mcpServers` config.
- `examples/mcp/servers/literature_server.py` — small local FastMCP server for
  examples.

**Tests**
- `easyagent/test/test_mcp.py` covers MCP tool discovery, ToolManager
  registration, tag filtering, server filtering, and result normalization.

### Changed

- `easyagent` top-level exports now include `MCPToolset`, `load_mcp_tools`,
  and `register_mcp_tools`.
- Default installation now includes sandbox, web, and MCP dependencies:
  `docker`, `httpx`, and `fastmcp`.
- `requirements.txt` now mirrors the default runtime dependency set.
- `README.md` and `README_CN.md` document MCP config loading and session-level
  tool enablement.
- MCP examples live under `examples/mcp/` instead of the numbered learning
  path, because MCP is an external integration rather than a core ladder step.

### Install

```bash
pip install -U easy-agent-sdk==0.5.1
```

MCP support is included in the default install.

---

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
