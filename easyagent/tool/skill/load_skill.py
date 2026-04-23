"""load_skill tool: fetches a skill's body and activates the tools it declares."""

from typing import Any

from easyagent.skill import SkillManager, get_active_agent
from easyagent.tool.manager import register_tool

_SKILL_BODY_CHAR_WARN = 20_000


@register_tool
class LoadSkill:
    """Load a skill by name, activate its declared tools, return its body."""

    name = "load_skill"
    type = "function"
    description = (
        "Load a skill's full instructions and activate the tools it enables. "
        "Call this only AFTER deciding a skill listed in 'Available Skills' is "
        "relevant. Returns the skill's markdown body."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact skill name as shown in 'Available Skills'.",
            }
        },
        "required": ["name"],
    }

    def init(self) -> None:
        pass

    def execute(self, name: str, **kwargs: Any) -> str:
        mgr = SkillManager()
        skill = mgr.get(name)
        if skill is None:
            return f"Error: skill '{name}' not found."

        agent = get_active_agent()
        activated: list[str] = []
        missing: list[str] = []
        if agent is not None and skill.tools:
            declared = list(skill.tools)
            activated = agent.enable_tools(declared)
            already = set(getattr(agent, "_tool_names", [])) - set(activated)
            missing = [t for t in declared if t not in activated and t not in already]

        try:
            body = skill.body()
        except OSError as e:
            return f"Error reading skill '{name}' body: {e}"

        header_lines = [f"# Skill: {skill.name}"]
        if activated:
            header_lines.append(f"Activated tools: {', '.join(activated)}")
        if missing:
            header_lines.append(
                f"Warning: declared tools not registered, skipped: {', '.join(missing)}"
            )
        if len(body) > _SKILL_BODY_CHAR_WARN:
            header_lines.append(
                f"Note: skill body is large (~{len(body) // 4} tokens); "
                "plan concisely before acting."
            )
        return "\n".join(header_lines) + "\n\n" + body
