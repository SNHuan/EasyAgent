"""SkillManager singleton with lazy discovery."""

import logging
import os
from pathlib import Path
from typing import Any

from easyagent.skill.base import Skill, SkillValidationError
from easyagent.skill.loader import load_skill_from_dir

_log = logging.getLogger(__name__)

SKILLS_DIR_ENV = "EA_SKILLS_DIR"
DEFAULT_SKILLS_DIR = ".easyagent/skills"


class SkillManager:
    """Registry of skills with lazy directory discovery."""

    def __init__(self, *, include_default_dirs: bool = True):
        self._skills: dict[str, Skill] = {}
        self._search_dirs: list[Path] = []
        self._discovered_dirs: set[Path] = set()
        self._defaults_queued = not include_default_dirs

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
        env_dirs = os.getenv(SKILLS_DIR_ENV)
        if env_dirs:
            for raw_dir in env_dirs.split(os.pathsep):
                if raw_dir.strip():
                    self.add_search_dir(raw_dir.strip())
            return
        self.add_search_dir(Path.cwd() / DEFAULT_SKILLS_DIR)

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
    """Convenience helper: register a Skill instance on the process default registry."""
    DEFAULT_SKILL_MANAGER.register(skill)
    return skill


DEFAULT_SKILL_MANAGER = SkillManager()


__all__: list[Any] = ["SkillManager", "DEFAULT_SKILL_MANAGER", "register_skill"]
