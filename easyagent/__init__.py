"""EasyAgent - A lightweight AI Agent framework built on LiteLLM."""

from easyagent.agent import ReactAgent, ToolAgent
from easyagent.memory import BaseMemory, SlidingWindowMemory, SummaryMemory
from easyagent.tool import Tool, ToolManager, register_tool

__version__ = "0.1.2"
__all__ = [
    # Agent
    "ReactAgent",
    "ToolAgent",
    # Memory
    "BaseMemory",
    "SlidingWindowMemory",
    "SummaryMemory",
    # Tool
    "Tool",
    "ToolManager",
    "register_tool",
]
