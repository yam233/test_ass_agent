"""
参数补全器

职责：
1. 从上下文推断参数
2. 从其他参数推断参数
3. 使用默认值填充
4. 提示用户补充（最后手段）

优势：
- 完全配置化，无硬编码
- 多层次补全策略
- 减少用户交互轮次
"""
from typing import Dict, Any, Optional, List
import re
import logging

logger = logging.getLogger(__name__)


class ParamCompletor:
    """参数补全器"""
    
    def __init__(self, business_code: str):
        """
        初始化参数补全器
        
        Args:
            business_code: 业务代码
        """
        self.business_code = business_code
        self.completion_strategies = {}
        self.global_rules = {}
        self.config = {}
        self._load_rules()
    
    def _load_rules(self):
        """加载参数补全规则"""
        try:
            from utils.config_loader_v2 import ConfigLoaderV2
            rules_config = ConfigLoaderV2.load_business_config(
                self.business_code,
                "param_completion_rules.json"
            )
            
            self.completion_strategies = rules_config.get("completion_strategies", {})
            self.global_rules = rules_config.get("global_rules", {})
            self.config = rules_config.get("config", {})
            
            logger.info(
                f"✓ 参数补全规则已加载: {len(self.completion_strategies)} 个 Skill "
                f"(business: {self.business_code})"
            )
        except Exception as e:
            logger.warning(f"加载参数补全规则失败: {e}")
            self.completion_strategies = {}
            self.global_rules = {}
            self.config = {}
    
    def complete_params(
        self,
        skill_name: str,
        raw_params: Dict[str, Any],
        param_schema: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        补全参数
        
        Args:
            skill_name: Skill 名称
            raw_params: 原始参数
            param_schema: 参数 Schema
            context: 上下文信息
            
        Returns:
            补全后的参数
        """
        if not self.config.get("enable_completion", True):
            logger.debug("参数补全已禁用")
            return raw_params
        
        completed_params = raw_params.copy()
        context = context or {}
        
        # 获取 Skill 的补全策略
        skill_strategies = self.completion_strategies.get(skill_name, {})
        
        # 遍历参数 Schema，补全缺失参数
        for param_name, param_def in param_schema.items():
            if param_name in completed_params:
                continue  # 参数已存在，跳过
            
            # 1. 尝试从上下文推断
            if self.config.get("enable_context_inference", True):
                value = self._infer_from_context(
                    param_name,
                    skill_strategies.get(param_name, {}),
                    context
                )
                if value is not None:
                    completed_params[param_name] = value
                    logger.debug(
                        f"从上下文补全参数: {param_name}={value}"
                    )
                    continue
            
            # 2. 尝试从其他参数推断
            if self.config.get("enable_param_inference", True):
                value = self._infer_from_params(
                    param_name,
                    skill_strategies.get(param_name, {}),
                    completed_params,
                    context
                )
                if value is not None:
                    completed_params[param_name] = value
                    logger.debug(
                        f"从其他参数推断: {param_name}={value}"
                    )
                    continue
            
            # 3. 尝试使用默认值
            if self.config.get("enable_default_values", True):
                value = self._get_default_value(
                    param_name,
                    skill_strategies.get(param_name, {}),
                    param_def
                )
                if value is not None:
                    completed_params[param_name] = value
                    logger.debug(
                        f"使用默认值: {param_name}={value}"
                    )
                    continue
            
            # 4. 检查是否必填
            if param_def.get("required", False):
                # 必填参数缺失，记录日志（由调用方处理）
                logger.warning(
                    f"必填参数缺失: {param_name} "
                    f"(skill: {skill_name})"
                )
        
        # 补全全局参数
        completed_params = self._complete_global_params(completed_params, context)
        
        return completed_params
    
    def _infer_from_context(
        self,
        param_name: str,
        strategy: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[Any]:
        """
        从上下文推断参数
        
        Args:
            param_name: 参数名
            strategy: 补全策略
            context: 上下文
            
        Returns:
            参数值，如果无法推断返回 None
        """
        context_keys = strategy.get("context_keys", [])
        
        for key in context_keys:
            if key in context and context[key] is not None:
                return context[key]
        
        return None
    
    def _infer_from_params(
        self,
        param_name: str,
        strategy: Dict[str, Any],
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[Any]:
        """
        从其他参数推断参数
        
        Args:
            param_name: 参数名
            strategy: 补全策略
            params: 已有参数
            context: 上下文
            
        Returns:
            参数值，如果无法推断返回 None
        """
        infer_from = strategy.get("infer_from")
        if not infer_from:
            return None
        
        # 检查源参数是否存在
        if infer_from not in params:
            return None
        
        source_value = params[infer_from]
        inference_rules = strategy.get("inference_rules", {})
        
        # 遍历推断规则
        for pattern, target_value in inference_rules.items():
            # 支持正则表达式匹配
            if pattern.startswith("^") or pattern.endswith("$"):
                if re.match(pattern, str(source_value)):
                    return target_value
            # 支持上下文引用（如 "context.room_id"）
            elif pattern.startswith("context."):
                context_key = pattern.replace("context.", "")
                if context_key in context and context[context_key] is not None:
                    return target_value
            # 精确匹配
            elif str(source_value) == pattern:
                return target_value
        
        return None
    
    def _get_default_value(
        self,
        param_name: str,
        strategy: Dict[str, Any],
        param_def: Dict[str, Any]
    ) -> Optional[Any]:
        """
        获取默认值
        
        Args:
            param_name: 参数名
            strategy: 补全策略
            param_def: 参数定义
            
        Returns:
            默认值，如果没有返回 None
        """
        # 优先使用策略中的默认值
        if "default" in strategy:
            return strategy["default"]
        
        # 其次使用 Schema 中的默认值
        if "default" in param_def:
            return param_def["default"]
        
        return None
    
    def _complete_global_params(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        补全全局参数
        
        Args:
            params: 参数字典
            context: 上下文
            
        Returns:
            补全后的参数
        """
        for param_name, rule in self.global_rules.items():
            if param_name in params:
                continue  # 参数已存在，跳过
            
            # 从上下文获取
            context_keys = rule.get("context_keys", [])
            for key in context_keys:
                if key in context and context[key] is not None:
                    params[param_name] = context[key]
                    logger.debug(
                        f"从上下文补全全局参数: {param_name}={context[key]}"
                    )
                    break
            
            # 使用默认值
            if param_name not in params and "default" in rule:
                params[param_name] = rule["default"]
                logger.debug(
                    f"使用默认值补全全局参数: {param_name}={rule['default']}"
                )
        
        return params
    
    def get_missing_params(
        self,
        params: Dict[str, Any],
        param_schema: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        获取缺失的必填参数
        
        Args:
            params: 参数字典
            param_schema: 参数 Schema
            
        Returns:
            缺失参数列表
        """
        missing = []
        
        for param_name, param_def in param_schema.items():
            if param_def.get("required", False) and param_name not in params:
                missing.append({
                    "name": param_name,
                    "type": param_def.get("type"),
                    "description": param_def.get("description", ""),
                    "prompt": param_def.get("prompt", f"请提供 {param_name}")
                })
        
        return missing
    
    def reload_rules(self):
        """重新加载规则（支持热更新）"""
        logger.info(f"重新加载参数补全规则 (business: {self.business_code})")
        self._load_rules()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        return {
            "business_code": self.business_code,
            "total_skills": len(self.completion_strategies),
            "global_rules": len(self.global_rules),
            "enabled": self.config.get("enable_completion", True),
            "context_inference": self.config.get("enable_context_inference", True),
            "param_inference": self.config.get("enable_param_inference", True),
            "default_values": self.config.get("enable_default_values", True)
        }
