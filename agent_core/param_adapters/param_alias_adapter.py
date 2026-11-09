"""
参数简称适配器

能力项：参数简称适配
输入：抽取的参数 + 简称映射规则
输出：标准化参数名/值（如 case123→TC-123）
实现：基于映射表 + 规则转换

处理参数简称/别名，如：
- "用户ID" → "user_id"
- "礼物id" → "gift_id"
- "case123" → "TC-123"
"""
from typing import Dict, Any


class ParamAliasAdapter:
    """处理参数简称/别名"""
    
    def adapt(self, params: Dict[str, Any], alias_rules: Dict[str, Any]) -> Dict[str, Any]:
        """
        参数简称适配：标准化参数名和值
        
        输入：
            params: 抽取的参数，如 {"用户ID": 123456, "case": "case123"}
            alias_rules: 简称映射规则，定义别名到标准名的映射
            
        输出：
            标准化参数名/值，如 {"user_id": 123456, "case_id": "TC-123"}
            
        实现：基于映射表进行参数名和值的转换
        """
        adapted_params = {}
        
        # 构建别名映射表（反向映射）
        alias_map = {}
        for standard_name, aliases in alias_rules.items():
            for alias in aliases:
                alias_map[alias.lower()] = standard_name
        
        # 转换参数名
        for param_name, value in params.items():
            # 检查是否是别名
            standard_name = alias_map.get(param_name.lower(), param_name)
            adapted_params[standard_name] = value
        
        return adapted_params
