"""
通用Skill调度核心
仅按协议匹配，无业务逻辑
"""
from typing import Dict, Any
from agent_core.protocol import SkillInput, SkillOutput


class SkillCore:
    """Skill调度核心"""
    
    def __init__(self):
        self.skills: Dict[str, Any] = {}
    
    def register_skill(self, business_code: str, skill_name: str, skill_instance):
        """
        注册Skill
        
        Args:
            business_code: 业务代码
            skill_name: Skill名称
            skill_instance: Skill实例
        """
        key = f"{business_code}:{skill_name}"
        self.skills[key] = skill_instance
    
    def execute_skill(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行Skill
        
        Args:
            skill_input: Skill输入协议
            
        Returns:
            Skill输出协议
        """
        key = f"{skill_input.business_code}:{skill_input.skill_name}"
        skill = self.skills.get(key)
        
        if not skill:
            return SkillOutput(
                success=False,
                error=f"Skill not found: {key}"
            )
        
        # 统一走 Skill 模板入口，确保风险控制/环境检查不被绕过
        if callable(skill):
            return skill(skill_input)
        return skill.execute(skill_input)
