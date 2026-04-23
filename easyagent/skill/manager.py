"""SkillManager singleton with lazy discovery."""

import logging
import os
from pathlib import Path
from typing import Any

from easyagent.skill.base import Skill, SkillValidationError
from easyagent.skill.loader import load_skill_from_dir

_log = logging.getLogger(__name__)


class SkillManager:
    """Singleton registry of skills, mirroring ToolManager's pattern."""

    _instance: "SkillManager | None" = None
    _skills: dict[str, Skill]
    _search_dirs: list[Path]
    _discovered_dirs: set[Path]
    _defaults_queued: bool

    def __new__(cls) -> "SkillManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills = {}
            cls._instance._search_dirs = []
            cls._instance._discovered_dirs = set()
            cls._instance._defaults_queued = False
        return cls._instance

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            _log.debug("Skill '%s' overwritten by registration from %s", skill.name, skill.path)
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        if name not in self._skills:
            self._ensure_discovered()
        return self._skills.get(name)

    def list_summaries(self, names: list[str] | None = None) -> list[dict[str, str]]:
        self._ensure_discovered()
        if names is None:
            return [s.summary() for s in self._skills.values()]
        out: list[dict[str, str]] = []
        for n in names:
            skill = self._skills.get(n)
            if skill is None:
                _log.warning("Skill '%s' not found; skipping", n)
                continue
            out.append(skill.summary())
        return out

    def load_body(self, name: str) -> str:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Skill '{name}' not found")
        return skill.body()

    def add_search_dir(self, directory: Path | str) -> None:
        path = Path(directory).expanduser().resolve()
        if path not in self._search_dirs:
            self._search_dirs.append(path)

    def discover(self, directory: Path | str | None = None) -> None:
        """Scan one directory (or all queued dirs) for SKILL.md subdirectories."""
        if directory is not None:
            self._scan_dir(Path(directory).expanduser().resolve())
            return
        self._ensure_defaults_queued()
        for d in list(self._search_dirs):
            self._scan_dir(d)

    def reset(self) -> None:
        """Clear all registered skills and discovery state. Tests only."""
        self._skills.clear()
        self._search_dirs.clear()
        self._discovered_dirs.clear()
        self._defaults_queued = False

    def _ensure_defaults_queued(self) -> None:
        if self._defaults_queued:
            return
        self._defaults_queued = True
        if env_dir := os.getenv("EA_SKILLS_DIR"):
            self.add_search_dir(env_dir)
        cwd_skills = Path.cwd() / "skills"
        self.add_search_dir(cwd_skills)

    def _ensure_discovered(self) -> None:
        self._ensure_defaults_queued()
        for d in list(self._search_dirs):
            if d not in self._discovered_dirs:
                self._scan_dir(d)

    def _scan_dir(self, directory: Path) -> None:
        self._discovered_dirs.add(directory)
        if not directory.is_dir():
            return
        for child in directory.iterdir():
            if not child.is_dir():
                continue
            if not (child / "SKILL.md").is_file():
                continue
            try:
                skill = load_skill_from_dir(child)
            except SkillValidationError as e:
                _log.warning("Failed to load skill at %s: %s", child, e)
                continue
            self.register(skill)


def register_skill(skill: Skill) -> Skill:
    """Convenience helper: register a Skill instance built in code."""
    SkillManager().register(skill)
    return skill


__all__: list[Any] = ["SkillManager", "register_skill"]
