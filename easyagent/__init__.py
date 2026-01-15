"""EasyAgent - A lightweight AI Agent framework built on LiteLLM."""

from easyagent.agent import ReactAgent, ToolAgent, SandboxAgent
from easyagent.memory import BaseMemory, SlidingWindowMemory, SummaryMemory
from easyagent.tool import Tool, ToolManager, register_tool
from easyagent.sandbox import (
    BaseSandbox,
    ExecResult,
    DockerSandbox,
    LocalSandbox,
    create_sandbox,
)

__version__ = "0.1.3"
__all__ = [
    # Agent
    "ReactAgent",
    "ToolAgent",
    "SandboxAgent",
    # Memory
    "BaseMemory",
    "SlidingWindowMemory",
    "SummaryMemory",
    # Tool
    "Tool",
    "ToolManager",
    "register_tool",
    # Sandbox
    "BaseSandbox",
    "ExecResult",
    "DockerSandbox",
    "LocalSandbox",
    "create_sandbox",
]
