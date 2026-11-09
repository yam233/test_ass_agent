"""
通用LLM代理（重构版）
职责：协调意图管理器和参数管理器，执行 Skill

重构说明：
- 拆分为 IntentManager（意图识别）和 ParameterManager（参数处理）
- 减少单一类复杂度，提高可维护性
- 保持向后兼容
"""
from typing import Dict, Any, Optional, List
import logging

from utils.config_loader import ConfigLoader
from agent_core.protocol import SkillInput, SkillOutput
from agent_core.managers import IntentManager, ParameterManager
from agent_core.helpers.user_prompt_helper import UserPromptHelper

logger = logging.getLogger(__name__)


class SkillAgent:
    """通用Skill代理 - LLM全流程驱动（重构版）"""
    
    def __init__(self, business_code: str, skill_core=None):
        self.business_code = business_code
        self.skill_core = skill_core
        
        # 加载配置
        self.skills_registry = self._load_skills_registry()
        self.param_rules = self._load_param_rules()
        self.prompts = self._load_prompts()
        
        # 延迟初始化管理器（避免启动时失败）
        self.llm_client = None
        self.intent_manager = None
        self.parameter_manager = None
    
    def _ensure_managers(self):
        """确保管理器已初始化"""
        if self.llm_client is None:
            try:
                from agent_core.parsers import LLMIntentParser
                from agent_core.extractors import LLMParamExtractor
                
                # 初始化共享的 LLM 客户端
                self.llm_client = ConfigLoader.create_llm_client()
                
                # 初始化解析器
                intent_parser = LLMIntentParser(self.llm_client)
                param_extractor = LLMParamExtractor(self.llm_client)
                
                # 初始化管理器
                self.intent_manager = IntentManager(
                    business_code=self.business_code,
                    llm_client=self.llm_client,
                    intent_parser=intent_parser
                )
                
                self.parameter_manager = ParameterManager(
                    business_code=self.business_code,
                    llm_client=self.llm_client,
                    param_extractor=param_extractor,
                    param_rules=self.param_rules
                )
                
                logger.info("✓ Agent 管理器初始化完成")
            except Exception as e:
                raise RuntimeError(
                    f"管理器初始化失败: {e}\n\n"
                    "请先修复依赖问题：\n"
                    "1. 运行: pip3 install --upgrade httpx\n"
                    "2. 或运行: ./fix_dependencies.sh"
                )
    
    def _load_skills_registry(self) -> Dict[str, Any]:
        """加载Skill注册表"""
        return ConfigLoader.load_business_config(
            self.business_code, 
            "skills_registry.json"
        )
    
    def _load_param_rules(self) -> Dict[str, Any]:
        """加载参数规则"""
        return ConfigLoader.load_business_config(
            self.business_code, 
            "param_rules.json"
        )
    
    def _load_prompts(self) -> Dict[str, str]:
        """加载Prompt模板"""
        import os
        prompts = {}
        prompt_path = f"references/business/{self.business_code}_prompt.md"
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompts['intent'] = f.read()
        return prompts
    
    def _get_available_skills(self) -> List[Dict[str, Any]]:
        """获取可用Skill列表"""
        skills = self.skills_registry.get("skills", [])
        return [
            {
                "skill_name": s["skill_name"],
                "display_name": s["display_name"],
                "description": s["description"],
                "skill_type": s["skill_type"]
            }
            for s in skills
        ]
    
    def _find_skill_config(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """查找Skill配置"""
        skills = self.skills_registry.get("skills", [])
        for skill in skills:
            if skill["skill_name"] == skill_name:
                return skill
        return None
    
    def process(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        处理用户请求 - LLM全流程驱动（重构版）
        
        流程：
        1. 环境检查
        2. 意图识别（IntentManager）
        3. 参数提取与适配（ParameterManager）
        4. 参数验证（ParameterManager）
        5. Skill 执行
        
        Args:
            user_input: 用户输入
            context: 上下文信息
            
        Returns:
            处理结果
        """
        try:
            # 0. 补齐上下文，确保下游参数提取可拿到 business_code
            if context is None:
                context = {}
            context["business_code"] = self.business_code

            # 1. 环境检查：仅支持 UAT 环境
            env = context.get("env", "uat")
            if env != "uat":
                return {
                    "success": False,
                    "error": "环境限制",
                    "message": f"系统仅支持 UAT 环境，当前环境: {env}。生产环境操作已被禁止。"
                }
            
            # 2. 确保管理器已初始化
            self._ensure_managers()
            
            # 3. 意图识别（使用 IntentManager）
            available_skills = self._get_available_skills()
            intent_result = self.intent_manager.recognize(
                user_input=user_input,
                available_skills=available_skills,
                context=context
            )
            
            # 检查置信度
            if intent_result.confidence < 0.5:
                return {
                    "success": False,
                    "error": "意图识别置信度过低",
                    "intent": intent_result.dict(),
                    "message": UserPromptHelper.get_unrecognized_command_reply()
                }
            
            # 4. 查找 Skill 配置
            skill_config = self._find_skill_config(intent_result.skill_name)
            if not skill_config:
                return {
                    "success": False,
                    "error": f"Skill未找到: {intent_result.skill_name}",
                    "intent": intent_result.dict(),
                    "message": UserPromptHelper.get_unrecognized_command_reply()
                }
            
            # 5. 参数提取与适配（使用 ParameterManager）
            param_schema = skill_config.get("param_schema", {})
            params = self.parameter_manager.extract_and_adapt(
                user_input=user_input,
                skill_name=intent_result.skill_name,
                param_schema=param_schema,
                context=context
            )
            
            # 6. 参数验证（使用 ParameterManager）
            validation_result = self.parameter_manager.validate(params, param_schema)
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": "参数验证失败",
                    "validation_errors": validation_result["errors"],
                    "intent": intent_result.dict(),
                    "params": params,
                    "message": f"参数错误: {', '.join(validation_result['errors'])}"
                }
            
            # 使用验证后的参数
            params = validation_result["params"]
            
            # 7. 调用 Skill Core 执行
            if self.skill_core:
                skill_input = SkillInput(
                    user_input=user_input,
                    business_code=self.business_code,
                    skill_name=intent_result.skill_name,
                    skill_type=skill_config["skill_type"],
                    params=params,
                    context=context
                )
                
                skill_output = self.skill_core.execute_skill(skill_input)
                final_message = skill_output.message or ("执行成功" if skill_output.success else "执行失败")
                
                return {
                    "success": skill_output.success,
                    "data": skill_output.data,
                    "message": final_message,
                    "error": skill_output.error,
                    "intent": intent_result.dict(),
                    "params": params,
                    "skill_name": intent_result.skill_name
                }
            else:
                return {
                    "success": True,
                    "intent": intent_result.dict(),
                    "params": params,
                    "skill_name": intent_result.skill_name,
                    "message": "Skill Core未初始化，仅返回解析结果"
                }
                
        except Exception as e:
            logger.error(f"处理异常: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": f"处理异常: {str(e)}"
            }
    
    # clear_cache 方法已移除，避免误操作Redis缓存
