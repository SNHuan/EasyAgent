"""EasyAgent — an incrementally designed agent SDK.

v0.5.0: MCP tool discovery and registration support.
Single-agent layer (Agent, ReactAgent, etc.) is unchanged.
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
from easyagent.model.schema import Message
from easyagent.mcp import MCPToolset, load_mcp_tools, register_mcp_tools
from easyagent.presets import chatroom, debate, fanout, groupchat, sequential
from easyagent.skill import SkillManager
from easyagent.tool import ToolManager, register_tool
from easyagent.worlds import (
    ConversationWorld,
    Grid2D,
    PipelineWorld,
    SharedState,
    SpatialWorld,
    StatefulWorld,
)

__version__ = "0.5.0"

__all__ = [
    # ── single-agent (unchanged) ───────────────────────────────────────
    "Agent",
    "AgentRunResult",
    "AgentSession",
    "ReactAgent",
    "SkillAgent",
    "SandboxAgent",
    "LiteLLMModel",
    "Message",
    "MessageEvent",
    "EventBus",
    "ToolManager",
    "SkillManager",
    "register_tool",
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
