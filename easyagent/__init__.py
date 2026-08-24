"""EasyAgent — an incrementally designed agent SDK.

v0.6.7: Adds dashboard custom hierarchy grouping for traced runs.
v0.6.6: Refines runtime tick execution and MCP structured result handling.
v0.6.5: Adds external Claude Code and Codex entities with dashboard tracing.
v0.6.4: Adds dashboard display hints for custom trace events.
v0.6.3: Polishes runtime dashboard timelines and navigation.
v0.6.2: Adds runtime-level tracing and runtime/entity/session dashboard trees.
v0.6.1: Improves live dashboard streaming traces and timeline display.
v0.6.0: Adds tracing persistence, streaming model responses, Agent Skills
loading, and the local dashboard CLI.
"""

from easyagent.agent import (
    Agent,
    AgentRunResult,
    AgentSession,
    ReactAgent,
    SandboxAgent,
    SessionNotResumableError,
    SkillAgent,
)
from easyagent.checkpoint import (
    AgentCheckpoint,
    CheckpointCompatibilityIssue,
    CheckpointCompatibilityReport,
    CheckpointStore,
    IncompatibleCheckpointError,
    InvalidCheckpointStateError,
    MemoryCheckpointStore,
    SQLiteCheckpointStore,
    UnsupportedCheckpointVersionError,
)
from easyagent.core import (
    Action,
    AllParallel,
    ChatMessage,
    Composite,
    Entity,
    LoopState,
    MaxTicks,
    MessagesSlice,
    Move,
    Perception,
    PerceptionSlice,
    RandomOrder,
    Reactive,
    RoundRobin,
    Runtime,
    RuntimeResult,
    Schedule,
    SetState,
    Silent,
    SpatialSlice,
    Speak,
    StateSlice,
    TakeTurns,
    UntilIdle,
    UntilPredicate,
    World,
)
from easyagent.entities import ExternalAgentEntity, HumanEntity, LLMEntity, TeamEntity
from easyagent.events import CustomTraceEvent, EventBus, MessageEvent
from easyagent.external import (
    ClaudeCodeRunner,
    CodexRunner,
    ExternalResult,
    ExternalRunRequest,
    ExternalRunner,
    LegacyExternalRunnerAdapter,
    claude_code_entity,
    codex_entity,
)
from easyagent.hooks import (
    AfterToolCallHook,
    BeforeToolCallHook,
    BeforeToolCallResult,
    HookManager,
)
from easyagent.model.litellm_model import LiteLLMModel
from easyagent.model.schema import LLMStreamChunk, Message
from easyagent.mcp import MCPToolset, load_mcp_tools, register_mcp_tools
from easyagent.presets import chatroom, debate, fanout, groupchat, sequential
from easyagent.skill import SkillManager
from easyagent.store import JSONLStore, MemoryStore, SQLiteStore, TraceStore
from easyagent.tool import Tool, ToolContext, ToolManager, ToolResult, register_tool
from easyagent.tracing import (
    DisplayHint,
    EventTrace,
    SessionTrace,
    TokenUsage,
    TraceRecorder,
    register_token_usage_adapter,
)
from easyagent.worlds import (
    ConversationWorld,
    Grid2D,
    PipelineWorld,
    SharedState,
    SpatialWorld,
    StatefulWorld,
)

__version__ = "0.6.7"

__all__ = [
    # ── single-agent (unchanged) ───────────────────────────────────────
    "Agent",
    "AgentRunResult",
    "AgentSession",
    "SessionNotResumableError",
    "AgentCheckpoint",
    "CheckpointCompatibilityIssue",
    "CheckpointCompatibilityReport",
    "CheckpointStore",
    "IncompatibleCheckpointError",
    "InvalidCheckpointStateError",
    "MemoryCheckpointStore",
    "SQLiteCheckpointStore",
    "UnsupportedCheckpointVersionError",
    "ReactAgent",
    "SkillAgent",
    "SandboxAgent",
    "LiteLLMModel",
    "LLMStreamChunk",
    "Message",
    "MessageEvent",
    "CustomTraceEvent",
    "EventBus",
    "HookManager",
    "BeforeToolCallHook",
    "BeforeToolCallResult",
    "AfterToolCallHook",
    "ToolManager",
    "Tool",
    "ToolContext",
    "ToolResult",
    "SkillManager",
    "register_tool",
    "TraceRecorder",
    "DisplayHint",
    "SessionTrace",
    "EventTrace",
    "TokenUsage",
    "register_token_usage_adapter",
    "TraceStore",
    "MemoryStore",
    "JSONLStore",
    "SQLiteStore",
    "MCPToolset",
    "load_mcp_tools",
    "register_mcp_tools",
    "ExternalResult",
    "ExternalRunRequest",
    "ExternalRunner",
    "LegacyExternalRunnerAdapter",
    "ClaudeCodeRunner",
    "CodexRunner",
    "claude_code_entity",
    "codex_entity",
    # ── core protocols ─────────────────────────────────────────────────
    "Entity",
    "World",
    "Schedule",
    "Runtime",
    "RuntimeResult",
    # ── perception & action types ──────────────────────────────────────
    "Perception",
    "PerceptionSlice",
    "MessagesSlice",
    "SpatialSlice",
    "StateSlice",
    "Action",
    "Speak",
    "Move",
    "SetState",
    "Silent",
    "Composite",
    "ChatMessage",
    "LoopState",
    # ── schedules ──────────────────────────────────────────────────────
    "TakeTurns",
    "AllParallel",
    "RoundRobin",
    "RandomOrder",
    "Reactive",
    "MaxTicks",
    "UntilIdle",
    "UntilPredicate",
    # ── worlds ─────────────────────────────────────────────────────────
    "ConversationWorld",
    "PipelineWorld",
    "SpatialWorld",
    "StatefulWorld",
    "Grid2D",
    "SharedState",
    # ── entities ───────────────────────────────────────────────────────
    "LLMEntity",
    "TeamEntity",
    "HumanEntity",
    "ExternalAgentEntity",
    # ── presets ─────────────────────────────────────────────────────────
    "sequential",
    "fanout",
    "debate",
    "chatroom",
    "groupchat",
]
