"""Skill module: progressive-disclosure capability packages."""

from easyagent.skill.base import Skill, SkillMeta, SkillValidationError
from easyagent.skill.loader import load_skill_from_dir, parse_frontmatter
from easyagent.skill.manager import SkillManager, register_skill

__all__ = [
    "Skill",
    "SkillMeta",
    "SkillValidationError",
    "SkillManager",
    "register_skill",
    "load_skill_from_dir",
    "parse_frontmatter",
]
