"""EasyAgent - an incrementally designed agent SDK.

The root package exposes the small stable SDK surface. Advanced building
blocks live in their submodules, for example ``easyagent.runtime`` or
``easyagent.context``.
"""

from easyagent.agent import Agent, AgentRunResult, AgentSession, ReactAgent, SandboxAgent, SkillAgent
from easyagent.events import EventBus, MessageEvent
from easyagent.model.litellm_model import LiteLLMModel
from easyagent.model.schema import Message
from easyagent.skill import SkillManager
from easyagent.tool import ToolManager, register_tool

__version__ = "0.3.0"

__all__ = [
    "Agent",
    "AgentRunResult",
    "AgentSession",
    "SkillAgent",
    "SandboxAgent",
    "ReactAgent",
    "LiteLLMModel",
    "Message",
    "MessageEvent",
    "EventBus",
    "ToolManager",
    "SkillManager",
    "register_tool",
]
