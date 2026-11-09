"""
业务启动入口 - 注册业务Skill
"""
import importlib
from typing import List, Type
from agent_core import SkillCore
from utils.config_loader import ConfigLoader


def _load_enabled_businesses() -> List[str]:
    """从框架配置加载启用的业务列表"""
    return ConfigLoader.load_enabled_businesses()


def _resolve_loader_class(business_code: str) -> Type:
    """按约定动态加载业务 Loader 类"""
    module_name = f"agent_plugins.{business_code}.{business_code}_loader"
    class_name = "".join(part.capitalize() for part in business_code.split("_")) + "Loader"

    module = importlib.import_module(module_name)
    loader_class = getattr(module, class_name, None)
    if loader_class is None:
        raise ValueError(f"未找到业务加载器类: {class_name} (module: {module_name})")
    return loader_class


def register_business_skills(skill_core: SkillCore, business_code: str):
    """注册指定业务的 Skill"""
    loader_class = _resolve_loader_class(business_code)
    loader = loader_class(business_code=business_code)
    loader.register_skills(skill_core)


def main():
    """初始化业务逻辑"""
    print("=" * 60)
    print("业务初始化开始...")
    print("=" * 60)
    
    skill_core = SkillCore()

    # 按配置注册业务
    businesses = _load_enabled_businesses()
    for business_code in businesses:
        register_business_skills(skill_core, business_code)
    
    print("\n" + "=" * 60)
    print("✓ 业务初始化完成")
    print("=" * 60)
    
    return skill_core


if __name__ == "__main__":
    main()
