"""EasyAgent — an incrementally designed agent SDK.

v0.6.0: Adds tracing persistence, streaming model responses, Agent Skills
loading, and the local dashboard CLI.
"""

from easyagent.agent import Agent, AgentRunResult, AgentSession, ReactAgent, SandboxAgent, SkillAgent
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
from easyagent.entities import HumanEntity, LLMEntity, TeamEntity
from easyagent.events import EventBus, MessageEvent
from easyagent.model.litellm_model import LiteLLMModel
from easyagent.model.schema import LLMStreamChunk, Message
from easyagent.mcp import MCPToolset, load_mcp_tools, register_mcp_tools
from easyagent.presets import chatroom, debate, fanout, groupchat, sequential
from easyagent.skill import SkillManager
from easyagent.store import JSONLStore, MemoryStore, SQLiteStore, TraceStore
from easyagent.tool import ToolManager, register_tool
from easyagent.tracing import EventTrace, SessionTrace, TokenUsage, TraceRecorder
from easyagent.worlds import (
    ConversationWorld,
    Grid2D,
    PipelineWorld,
    SharedState,
    SpatialWorld,
    StatefulWorld,
)

__version__ = "0.6.0"

__all__ = [
    # ── single-agent (unchanged) ───────────────────────────────────────
    "Agent",
    "AgentRunResult",
    "AgentSession",
    "ReactAgent",
    "SkillAgent",
    "SandboxAgent",
    "LiteLLMModel",
    "LLMStreamChunk",
    "Message",
    "MessageEvent",
    "EventBus",
    "ToolManager",
    "SkillManager",
    "register_tool",
    "TraceRecorder",
    "SessionTrace",
    "EventTrace",
    "TokenUsage",
    "TraceStore",
    "MemoryStore",
    "JSONLStore",
    "SQLiteStore",
    "MCPToolset",
    "load_mcp_tools",
    "register_mcp_tools",
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
    # ── presets ─────────────────────────────────────────────────────────
    "sequential",
    "fanout",
    "debate",
    "chatroom",
    "groupchat",
]
