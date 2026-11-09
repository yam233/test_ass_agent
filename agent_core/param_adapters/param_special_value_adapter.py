"""
特殊值适配器

处理特殊值映射，如：
- "永久" → 1000
- "一周" → 7
- "一个月" → 30
"""
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ParamSpecialValueAdapter:
    """特殊值适配器 - 处理特殊值映射（如"永久"→1000）"""
    
    def adapt(
        self, 
        params: Dict[str, Any], 
        param_schema: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        适配特殊值
        
        Args:
            params: 参数字典
            param_schema: 参数 Schema
            context: 上下文信息
            
        Returns:
            适配后的参数
        """
        adapted_params = params.copy()
        
        for param_name, param_def in param_schema.items():
            if param_name not in adapted_params:
                continue
            
            value = adapted_params[param_name]
            if value is None:
                continue
            
            # 获取特殊值映射
            special_values = param_def.get("special_values", {})
            if not special_values:
                continue
            
            # 检查是否匹配特殊值
            if isinstance(value, str):
                for special_key, special_val in special_values.items():
                    if special_key in value or value == special_key:
                        logger.debug(
                            f"特殊值适配: {param_name}={value} → {special_val}"
                        )
                        adapted_params[param_name] = special_val
                        break
        
        return adapted_params
