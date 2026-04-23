from __future__ import annotations

from pathlib import Path
from typing import Any

from easyagent.capability.base import BaseCapability
from easyagent.prompt.react import build_skills_section
from easyagent.skill import SkillManager
from easyagent.tool import ToolManager


class SkillCapability(BaseCapability):
    def __init__(self, skills: list[str], skill_dir: str | Path | None = None):
        self._skill_names = list(skills)
        self._skill_dir = Path(skill_dir).expanduser().resolve() if skill_dir else None
        self._skills = SkillManager()
        self._tools = ToolManager()

    def on_attach(self, agent: Any) -> None:
        if self._skill_dir is not None:
            self._skills.add_search_dir(self._skill_dir)

    def get_system_prompt_parts(self, agent: Any, session: Any) -> list[str]:
        summaries = self._skills.list_summaries(self._skill_names)
        section = build_skills_section(summaries)
        return [section] if section else []

    def get_tool_schemas(self, agent: Any, session: Any) -> list[dict[str, Any]]:
        if not self._skill_names:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": (
                        "Load a skill's full instructions and activate the tools it enables."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Exact skill name shown in the available skills list.",
                            }
                        },
                        "required": ["name"],
                    },
                },
            }
        ]

    async def handle_tool_call(
        self,
        agent: Any,
        session: Any,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        if tool_name != "load_skill":
            return None

        skill_name = str(arguments.get("name", ""))
        skill = self._skills.get(skill_name)
        if skill is None:
            return f"Error: skill '{skill_name}' not found."

        activated: list[str] = []
        missing: list[str] = []
        for declared_tool in skill.tools:
            if self._tools.get(declared_tool) is None:
                missing.append(declared_tool)
                continue
            if declared_tool not in session.enabled_tools:
                session.enabled_tools.append(declared_tool)
                activated.append(declared_tool)

        if skill_name not in session.loaded_skills:
            session.loaded_skills.append(skill_name)

        body = skill.body()
        header = [f"# Skill: {skill.name}"]
        if activated:
            header.append(f"Activated tools: {', '.join(activated)}")
        if missing:
            header.append(f"Warning: declared tools not registered: {', '.join(missing)}")
        return "\n".join(header) + "\n\n" + body
