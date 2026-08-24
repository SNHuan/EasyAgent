from __future__ import annotations

from pathlib import Path
from typing import Any

from easyagent.agent.react_agent import ReactAgent
from easyagent.skill import DEFAULT_SKILL_MANAGER, SkillManager


class SkillAgent(ReactAgent):
    """ReactAgent + on-demand skill loading from SKILL.md packages.

    Skills are declared by name; their instructions and tools are loaded
    lazily when the LLM calls the ``load_skill`` tool.

    Usage::

        agent = SkillAgent(
            model=m,
            tools=[get_weather],
            skills=["my-skill"],
            # Defaults to .easyagent/skills; set EA_SKILLS_DIR for .claude/skills, etc.
        )
    """

    def __init__(
        self,
        model: Any,
        *,
        skills: list[str] | None = None,
        skill_root: str | Path | None = None,
        skill_manager: SkillManager | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            model,
            skills=skills,
            skill_root=skill_root,
            skill_manager=skill_manager or DEFAULT_SKILL_MANAGER,
            **kwargs,
        )
