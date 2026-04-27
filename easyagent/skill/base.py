"""Skill data model."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


class SkillValidationError(ValueError):
    """Raised when SKILL.md frontmatter is missing required keys or malformed."""


@dataclass(frozen=True)
class SkillMeta:
    """Parsed SKILL.md frontmatter."""

    name: str
    description: str
    tools: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    version: str | None = None
    extras: dict = field(default_factory=dict)


class Skill:
    """A capability package. Body is lazy-loaded on first access."""

    def __init__(self, meta: SkillMeta, path: Path):
        self._meta = meta
        self._path = path
        self._body: str | None = None

    @property
    def name(self) -> str:
        return self._meta.name

    @property
    def description(self) -> str:
        return self._meta.description

    @property
    def tools(self) -> tuple[str, ...]:
        return self._meta.tools

    @property
    def triggers(self) -> tuple[str, ...]:
        return self._meta.triggers

    @property
    def path(self) -> Path:
        return self._path

    @property
    def meta(self) -> SkillMeta:
        return self._meta

    def body(self) -> str:
        if self._body is None:
            from easyagent.skill.loader import parse_frontmatter

            text = (self._path / "SKILL.md").read_text(encoding="utf-8")
            _, body = parse_frontmatter(text)
            self._body = body.strip()
        return self._body

    def list_files(self) -> list[str]:
        """List non-SKILL.md files packaged with this skill."""
        files: list[str] = []
        for path in self._iter_package_files():
            rel = path.relative_to(self._path).as_posix()
            if rel == "SKILL.md":
                continue
            files.append(rel)
        return sorted(files)

    def read_file(self, relative_path: str) -> str:
        """Read a packaged skill file by relative path."""
        path = self.resolve_file(relative_path)
        return path.read_text(encoding="utf-8")

    def resolve_file(self, relative_path: str) -> Path:
        """Resolve a skill-local path and prevent escaping the skill folder."""
        normalized = relative_path.strip().replace("\\", "/")
        if not normalized:
            raise ValueError("relative_path is required")
        path = (self._path / normalized).resolve()
        root = self._path.resolve()
        if path == root or root not in path.parents:
            raise ValueError(f"Path escapes skill directory: {relative_path}")
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        return path

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}

    def _iter_package_files(self) -> Iterable[Path]:
        ignored_dirs = {"__pycache__", ".git", ".venv", "node_modules"}
        for path in self._path.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignored_dirs for part in path.relative_to(self._path).parts):
                continue
            yield path
