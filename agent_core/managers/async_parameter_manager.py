"""
异步参数管理器

职责：
1. 异步 LLM 参数提取
2. 参数补全（智能补全缺失参数）
3. 参数适配（格式/别名/指代/特殊值）
4. 参数验证

优化（2025-02-16）：
- 添加参数智能补全
- 从上下文推断
- 从其他参数推断
- 使用默认值
"""
from typing import Dict, Any, Optional
import logging

from agent_core.param_adapters import (
    ParamFormatAdapter,
    ParamAliasAdapter,
    ParamReferenceAdapter,
    ParamSpecialValueAdapter
)
from agent_core.managers.param_validator import ParamValidator

logger = logging.getLogger(__name__)


class AsyncParameterManager:
    """异步参数管理器 - 负责参数提取、补全、适配和验证"""
    
    def __init__(
        self, 
        business_code: str, 
        async_llm_client,
        async_param_extractor,
        param_rules: Dict[str, Any]
    ):
        """
        初始化异步参数管理器
        
        Args:
            business_code: 业务代码
            async_llm_client: 异步 LLM 客户端实例（共享）
            async_param_extractor: 异步参数提取器实例
            param_rules: 参数规则配置
        """
        self.business_code = business_code
        self.llm_client = async_llm_client
        self.param_extractor = async_param_extractor
        self.param_rules = param_rules
        
        # 初始化参数补全器（同步，因为补全逻辑很快）
        self.param_completor = None
        try:
            from agent_core.extractors.param_completor import ParamCompletor
            self.param_completor = ParamCompletor(business_code)
            logger.info("✓ 异步参数补全器已启用")
        except Exception as e:
            logger.warning(f"异步参数补全器初始化失败: {e}")
        
        # 初始化适配器链（按顺序执行）
        self.adapters = [
            ParamFormatAdapter(),        # 1. 格式适配
            ParamAliasAdapter(),          # 2. 别名适配
            ParamReferenceAdapter(),      # 3. 指代消解
            ParamSpecialValueAdapter()    # 4. 特殊值处理
        ]
    
    async def extract_and_adapt(
        self, 
        user_input: str, 
        skill_name: str,
        param_schema: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        异步提取、补全并适配参数
        
        Args:
            user_input: 用户输入
            skill_name: Skill 名称
            param_schema: 参数 Schema
            context: 上下文信息
            
        Returns:
            适配后的参数
        """
        # 1. 异步 LLM 提取原始参数
        raw_params = await self.param_extractor.extract_params(
            user_input,
            skill_name,
            param_schema,
            context=context
        )
        logger.debug(f"原始参数: {raw_params}")
        
        # 2. 参数补全（同步，因为补全逻辑很快）
        if self.param_completor:
            completed_params = self.param_completor.complete_params(
                skill_name,
                raw_params,
                param_schema,
                context=context
            )
            logger.debug(f"补全后参数: {completed_params}")
        else:
            completed_params = raw_params
        
        # 3. 依次执行适配器链
        adapted_params = completed_params
        for adapter in self.adapters:
            if isinstance(adapter, ParamFormatAdapter):
                format_rules = self.param_rules.get("format_rules", {})
                adapted_params = adapter.adapt(adapted_params, format_rules)
            elif isinstance(adapter, ParamAliasAdapter):
                alias_rules = self.param_rules.get("alias_rules", {})
                adapted_params = adapter.adapt(adapted_params, alias_rules)
            elif isinstance(adapter, ParamReferenceAdapter):
                adapted_params = adapter.adapt(adapted_params, context)
            elif isinstance(adapter, ParamSpecialValueAdapter):
                adapted_params = adapter.adapt(adapted_params, param_schema, context)
        
        logger.debug(f"适配后参数: {adapted_params}")
        return adapted_params
    
    def validate(
        self, 
        params: Dict[str, Any], 
        param_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证参数
        
        Args:
            params: 参数字典
            param_schema: 参数 Schema
            
        Returns:
            验证结果 {valid: bool, errors: list}
        """
        return ParamValidator.validate(params, param_schema)
    
