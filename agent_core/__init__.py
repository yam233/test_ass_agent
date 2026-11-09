"""Agent核心框架"""
from .skill_core import SkillCore

__all__ = ["SkillCore", "SkillAgent"]


def __getattr__(name):
    if name == "SkillAgent":
        from .skill_agent import SkillAgent
        return SkillAgent
    raise AttributeError(f"module 'agent_core' has no attribute {name!r}")
