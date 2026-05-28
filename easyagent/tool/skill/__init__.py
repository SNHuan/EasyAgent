"""Skill-related tools: load_skill, list_skill_files, read_skill_file, run_skill_script."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from easyagent.skill.manager import SkillManager


class LoadSkillTool:
    name = "load_skill"
    type = "function"
    description = "Load a skill's full instructions and enable any registered tools it allows."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact skill name shown in the available skills list."},
        },
        "required": ["name"],
    }

    def __init__(self, skill_manager: SkillManager, allowed_names: list[str]):
        self._skills = skill_manager
        self._allowed = allowed_names

    def init(self) -> None:
        pass

    async def execute(self, name: str = "", *, session: Any | None = None, **kwargs: Any) -> str:
        skill_name = name.strip()
        skill = self._skills.get(skill_name)
        if skill is None:
            return f"Error: skill '{skill_name}' not found."

        activated: list[str] = []
        missing: list[str] = []
        if session is not None:
            for declared_tool in skill.tools:
                tool = getattr(session.agent, "_tool_manager", None).get(declared_tool) if session.agent else None
                if tool is None:
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
            header.append(f"Declared tools not registered: {', '.join(missing)}")
        files = skill.list_files()
        if files:
            header.append("Available packaged files:")
            header.extend(f"- {path}" for path in files)
        return "\n".join(header) + "\n\n" + body


class ListSkillFilesTool:
    name = "list_skill_files"
    type = "function"
    description = "List packaged files for a loaded skill."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Loaded skill name."},
        },
        "required": ["name"],
    }

    def __init__(self, skill_manager: SkillManager):
        self._skills = skill_manager

    def init(self) -> None:
        pass

    def execute(self, name: str = "", *, session: Any | None = None, **kwargs: Any) -> str:
        skill_name = name.strip()
        if session is not None and skill_name not in session.loaded_skills:
            return f"Error: skill '{skill_name}' is not loaded. Call load_skill first."
        skill = self._skills.get(skill_name)
        if skill is None:
            return f"Error: skill '{skill_name}' not found."
        files = skill.list_files()
        if not files:
            return f"Skill '{skill.name}' has no packaged files."
        return "\n".join(files)


class ReadSkillFileTool:
    name = "read_skill_file"
    type = "function"
    description = "Read a packaged file from a loaded skill."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Loaded skill name."},
            "path": {"type": "string", "description": "Path relative to the skill directory."},
        },
        "required": ["name", "path"],
    }

    def __init__(self, skill_manager: SkillManager):
        self._skills = skill_manager

    def init(self) -> None:
        pass

    def execute(self, name: str = "", path: str = "", *, session: Any | None = None, **kwargs: Any) -> str:
        skill_name = name.strip()
        if session is not None and skill_name not in session.loaded_skills:
            return f"Error: skill '{skill_name}' is not loaded. Call load_skill first."
        skill = self._skills.get(skill_name)
        if skill is None:
            return f"Error: skill '{skill_name}' not found."
        try:
            return skill.read_file(path.strip())
        except Exception as exc:
            return f"Error reading skill file '{path}': {exc}"


class RunSkillScriptTool:
    name = "run_skill_script"
    type = "function"
    description = "Run a script from a loaded skill's scripts directory."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Loaded skill name."},
            "script": {"type": "string", "description": "Script path under scripts/, for example helper.py."},
            "args": {"type": "array", "items": {"type": "string"}, "description": "Command line arguments."},
        },
        "required": ["name", "script"],
    }

    def __init__(self, skill_manager: SkillManager):
        self._skills = skill_manager

    def init(self) -> None:
        pass

    async def execute(
        self, name: str = "", script: str = "", args: list[str] | None = None,
        *, session: Any | None = None, **kwargs: Any,
    ) -> str:
        skill_name = name.strip()
        if session is not None and skill_name not in session.loaded_skills:
            return f"Error: skill '{skill_name}' is not loaded. Call load_skill first."
        skill = self._skills.get(skill_name)
        if skill is None:
            return f"Error: skill '{skill_name}' not found."
        script_path_str = script.strip().replace("\\", "/")
        if not script_path_str.startswith("scripts/"):
            script_path_str = f"scripts/{script_path_str}"
        try:
            script_path = skill.resolve_file(script_path_str)
        except Exception as exc:
            return f"Error resolving skill script '{script_path_str}': {exc}"
        cmd = ["python", str(script_path), *(str(a) for a in (args or []))]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(skill.path),
        )
        stdout, stderr = await proc.communicate()
        result = {
            "exit_code": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }
        return json.dumps(result, ensure_ascii=False)
