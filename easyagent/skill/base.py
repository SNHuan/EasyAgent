"""Skill data model."""

from dataclasses import dataclass, field
from pathlib import Path


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

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}
