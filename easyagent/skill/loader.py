"""SKILL.md frontmatter parsing and directory loading."""

import re
from pathlib import Path

import yaml

from easyagent.skill.base import Skill, SkillMeta, SkillValidationError

_FRONTMATTER_DELIM = re.compile(r"(?m)^---\s*$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split '---\\n<yaml>\\n---\\n<body>' into (meta_dict, body).

    Returns ({}, text) if no frontmatter block is present.
    Raises SkillValidationError when frontmatter exists but contains invalid YAML.
    """
    if not text.lstrip().startswith("---"):
        return {}, text

    parts = _FRONTMATTER_DELIM.split(text, maxsplit=2)
    if len(parts) < 3:
        return {}, text

    _, front, body = parts
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError as e:
        raise SkillValidationError(f"Invalid YAML frontmatter: {e}") from e

    if not isinstance(meta, dict):
        raise SkillValidationError(
            f"Frontmatter must be a YAML mapping, got {type(meta).__name__}"
        )
    return meta, body


def _coerce_str_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(x) for x in value)
    raise SkillValidationError(f"Expected string or list of strings, got {type(value).__name__}")


def _build_meta(raw: dict, source: Path) -> SkillMeta:
    known_keys = {"name", "description", "allowed-tools", "tools", "triggers", "version"}

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise SkillValidationError(f"{source}: 'name' is required and must be a non-empty string")
    if not _NAME_RE.match(name):
        raise SkillValidationError(
            f"{source}: skill name '{name}' must match {_NAME_RE.pattern} "
            "(1-64 chars; lowercase letters, digits, hyphen, underscore)"
        )
    parent_name = source.parent.name
    if name != parent_name:
        raise SkillValidationError(
            f"{source}: skill name '{name}' must match parent directory '{parent_name}'"
        )

    description = raw.get("description")
    if not isinstance(description, str) or not description:
        raise SkillValidationError(
            f"{source}: 'description' is required and must be a non-empty string"
        )

    tools = _coerce_str_tuple(raw.get("allowed-tools", raw.get("tools")))
    triggers = _coerce_str_tuple(raw.get("triggers"))

    version = raw.get("version")
    if version is not None and not isinstance(version, str):
        version = str(version)

    extras = {k: v for k, v in raw.items() if k not in known_keys}

    return SkillMeta(
        name=name,
        description=description,
        tools=tools,
        triggers=triggers,
        version=version,
        extras=extras,
    )


def load_skill_from_dir(skill_dir: Path) -> Skill:
    """Read <skill_dir>/SKILL.md and build a Skill (body stays lazy)."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillValidationError(f"No SKILL.md found in {skill_dir}")

    text = skill_md.read_text(encoding="utf-8")
    raw, _ = parse_frontmatter(text)
    if not raw:
        raise SkillValidationError(f"{skill_md}: frontmatter is missing")

    meta = _build_meta(raw, skill_md)
    return Skill(meta=meta, path=skill_dir)
