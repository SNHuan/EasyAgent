"""Skill module: progressive-disclosure capability packages."""

from contextvars import ContextVar
from typing import TYPE_CHECKING

from easyagent.skill.base import Skill, SkillMeta, SkillValidationError
from easyagent.skill.loader import load_skill_from_dir, parse_frontmatter
from easyagent.skill.manager import SkillManager, register_skill

if TYPE_CHECKING:
    from easyagent.agent.tool_agent import ToolAgent

__all__ = [
    "Skill",
    "SkillMeta",
    "SkillValidationError",
    "SkillManager",
    "register_skill",
    "load_skill_from_dir",
    "parse_frontmatter",
    "get_active_agent",
    "agent_context",
]

_active_agent_var: ContextVar["ToolAgent | None"] = ContextVar(
    "active_tool_agent", default=None
)


def get_active_agent() -> "ToolAgent | None":
    """Return the ToolAgent running on the current task, if any."""
    return _active_agent_var.get()


class agent_context:
    """Context manager that publishes the running agent so tools can reach back."""

    def __init__(self, agent: "ToolAgent | None"):
        self._agent = agent
        self._token = None

    def __enter__(self):
        self._token = _active_agent_var.set(self._agent)
        return self

    def __exit__(self, *args):
        if self._token is not None:
            _active_agent_var.reset(self._token)
