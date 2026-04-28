from __future__ import annotations

from pathlib import Path
from typing import Any

from easyagent.agent.react_agent import ReactAgent
from easyagent.agent.session import AgentSession
from easyagent.prompt.react import build_skills_section
from easyagent.skill import DEFAULT_SKILL_MANAGER, SkillManager
from easyagent.tool.skill import (
    ListSkillFilesTool,
    LoadSkillTool,
    ReadSkillFileTool,
    RunSkillScriptTool,
)


class SkillAgent(ReactAgent):
    """ReactAgent + on-demand skill loading from SKILL.md packages.

    Skills are declared by name; their instructions and tools are loaded
    lazily when the LLM calls the ``load_skill`` tool.

    Usage::

        agent = SkillAgent(
            model=m,
            tools=[get_weather],
            skills=["my-skill"],
            skill_root="./skills",
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
        super().__init__(model, **kwargs)
        self._skill_manager = skill_manager or DEFAULT_SKILL_MANAGER
        self._skill_names = list(skills or [])
        if skill_root is not None:
            self._skill_manager.add_search_dir(Path(skill_root))
        if self._skill_names:
            self.add_tool(LoadSkillTool(self._skill_manager, self._skill_names))
            self.add_tool(ListSkillFilesTool(self._skill_manager))
            self.add_tool(ReadSkillFileTool(self._skill_manager))
            self.add_tool(RunSkillScriptTool(self._skill_manager))

    def build_system_prompt(self, session: AgentSession) -> str:
        base = super().build_system_prompt(session)
        summaries = self._skill_manager.list_summaries(self._skill_names)
        section = build_skills_section(summaries)
        if section:
            return "\n\n".join([base, section])
        return base
