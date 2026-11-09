"""
AI测试助手业务加载器
负责加载配置、注册Skills到SkillCore
"""
from typing import Dict, Any
from agent_core import SkillCore
from utils.config_loader import ConfigLoader
from .skills.skill_factory import SkillFactory


class TestOpsLoader:
    """AI测试助手业务加载器"""
    
    def __init__(self, business_code: str = "testops"):
        self.business_code = business_code
        self.skills_registry = self._load_skills_registry()
        self.mcp_registry = self._load_mcp_registry()
    
    def _load_skills_registry(self) -> Dict[str, Any]:
        """加载Skill注册表"""
        return ConfigLoader.load_business_config(
            self.business_code,
            "skills_registry.json"
        )
    
    def _load_mcp_registry(self) -> Dict[str, Any]:
        """加载MCP服务注册表"""
        return ConfigLoader.load_business_config(
            self.business_code,
            "mcp_registry.json"
        )
    
    def register_skills(self, skill_core: SkillCore):
        """
        注册所有Skills到SkillCore
        
        Args:
            skill_core: SkillCore实例
        """
        skills = self.skills_registry.get("skills", [])
        
        for skill_config in skills:
            try:
                # 使用工厂创建Skill实例
                skill_instance = SkillFactory.create_skill(
                    skill_config,
                    self.mcp_registry,
                    self.business_code
                )
                
                # 注册到SkillCore
                skill_core.register_skill(
                    self.business_code,
                    skill_config["skill_name"],
                    skill_instance
                )
                
                print(f"✓ 注册Skill: {skill_config['skill_name']} ({skill_config['display_name']})")
                
            except Exception as e:
                print(f"✗ 注册Skill失败: {skill_config['skill_name']}, 错误: {e}")
        
        print(f"\n✓ AI测试助手业务加载完成，共注册 {len(skills)} 个Skills")
