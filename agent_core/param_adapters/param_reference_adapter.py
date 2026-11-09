"""
参数指代适配器

能力项：参数指代适配
输入：抽取的参数 + 上下文 + 指代规则
输出：补全指代参数（如 "它"→case_id）
实现：基于上下文 + 指代消解

处理参数指代消解，如：
- "它" → case_id (从上下文获取)
- "他" → user_id (从上下文获取)
- "这个" → gift_id (从上下文获取)
"""
from typing import Dict, Any, Optional


class ParamReferenceAdapter:
    """处理参数指代消解"""
    
    def adapt(
        self, 
        params: Dict[str, Any], 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        参数指代适配：补全指代参数
        
        输入：
            params: 抽取的参数，如 {"action": "查询", "target": "它"}
            context: 上下文，如 {"last_case_id": "TC-123"}
            
        输出：
            补全指代参数，如 {"action": "查询", "case_id": "TC-123"}
            
        实现：基于上下文进行指代消解
        """
        if not context:
            return params
        
        adapted_params = params.copy()
        
        # 指代词列表
        pronouns = ["它", "这个", "那个", "上面的", "刚才的", "他", "她"]
        
        # 处理指代消解
        for param_name, value in params.items():
            if isinstance(value, str) and value in pronouns:
                # 尝试从上下文获取实际值
                resolved_value = self._resolve_reference(param_name, value, context)
                if resolved_value is not None:
                    adapted_params[param_name] = resolved_value
        
        return adapted_params
    
    def _resolve_reference(
        self, 
        param_name: str, 
        pronoun: str, 
        context: Dict[str, Any]
    ) -> Optional[Any]:
        """
        消解指代
        
        Args:
            param_name: 参数名
            pronoun: 指代词
            context: 上下文
            
        Returns:
            消解后的值
        """
        # 从上下文的历史记录中查找
        history = context.get("history", [])
        if not history:
            return None
        
        # 获取最近一次的参数值
        for record in reversed(history):
            params = record.get("params", {})
            if param_name in params:
                return params[param_name]
        
        return None
