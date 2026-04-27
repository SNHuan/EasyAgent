"""Skill module: progressive-disclosure capability packages."""

from easyagent.skill.base import Skill, SkillMeta, SkillValidationError
from easyagent.skill.loader import load_skill_from_dir, parse_frontmatter
from easyagent.skill.manager import DEFAULT_SKILL_MANAGER, SkillManager, register_skill

__all__ = [
    "Skill",
    "SkillMeta",
    "SkillValidationError",
    "SkillManager",
    "DEFAULT_SKILL_MANAGER",
    "register_skill",
    "load_skill_from_dir",
    "parse_frontmatter",
]
