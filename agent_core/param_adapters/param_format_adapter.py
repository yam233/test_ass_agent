"""
参数格式适配器

能力项：参数格式适配
输入：抽取的参数 + 通用格式规则
输出：标准化格式参数（如时间戳→日期）
实现：基于规则引擎 + 格式转换

处理参数格式转换，如：
- 时间戳 → 日期格式
- 字符串 → 数字
- "7天" → 7
- 正则表达式验证
"""
from typing import Dict, Any, Optional
import re


class ParamFormatAdapter:
    """处理参数格式转换"""
    
    def adapt(self, params: Dict[str, Any], format_rules: Dict[str, Any]) -> Dict[str, Any]:
        """
        参数格式适配：标准化参数格式
        
        输入：
            params: 抽取的参数，如 {"user_id": "123456", "duration": "7天"}
            format_rules: 通用格式规则，定义转换规则和验证规则
            
        输出：
            标准化格式参数，如 {"user_id": 123456, "duration_days": 7}
            
        实现：基于规则引擎进行格式转换和验证
        """
        adapted_params = params.copy()
        
        for param_name, value in params.items():
            if value is None or value == "":
                continue
            
            # 应用格式规则
            rule = format_rules.get(param_name)
            if rule:
                # 正则表达式验证
                if isinstance(rule, str) and rule.startswith("^"):
                    if not self._validate_regex(value, rule):
                        print(f"警告: 参数 {param_name} 值 {value} 不符合格式规则 {rule}")
                        continue
            
            # 自动类型转换
            adapted_params[param_name] = self._auto_convert(param_name, value)
        
        return adapted_params
    
    def _validate_regex(self, value: Any, pattern: str) -> bool:
        """
        正则表达式验证
        
        Args:
            value: 参数值
            pattern: 正则表达式
            
        Returns:
            是否匹配
        """
        try:
            return bool(re.match(pattern, str(value)))
        except (re.error, TypeError, ValueError) as e:
            print(f"警告: 正则表达式验证失败 - pattern={pattern}, value={value}, error={e}")
            return False
    
    def _auto_convert(self, param_name: str, value: Any) -> Any:
        """
        自动类型转换
        
        Args:
            param_name: 参数名
            value: 参数值
            
        Returns:
            转换后的值
        """
        # 时长转换（如 "7天" → 7）- 优先处理
        if param_name == "duration_days" and isinstance(value, str) and not value.isdigit():
            return self._parse_duration(value)
        
        # 数字类型参数
        if param_name in ["user_id", "room_id", "gift_id", "num", "duration_days", 
                          "batch_count", "reward_id", "element_id", "pool_id"]:
            return self._to_int(value)
        
        # 手机号格式化
        elif param_name in ["phone", "mobile"]:
            return self._format_phone(value)
        
        # 邮箱格式化
        elif param_name == "email":
            return self._format_email(value)
        
        return value
    
    def _to_int(self, value: Any) -> Optional[int]:
        """
        转换为整数
        
        Args:
            value: 参数值
            
        Returns:
            整数值或None
        """
        try:
            if isinstance(value, int):
                return value
            elif isinstance(value, str):
                # 移除空格和逗号
                cleaned = value.strip().replace(",", "")
                return int(cleaned)
            elif isinstance(value, float):
                return int(value)
        except (ValueError, AttributeError) as e:
            print(f"警告: 整数转换失败 - value={value}, error={e}")
        return None
    
    def _format_phone(self, value: str) -> str:
        """
        格式化手机号
        
        Args:
            value: 手机号
            
        Returns:
            格式化后的手机号
        """
        # 移除空格、横线等
        phone = re.sub(r'[\s\-\(\)]', '', str(value))
        return phone
    
    def _format_email(self, value: str) -> str:
        """
        格式化邮箱
        
        Args:
            value: 邮箱
            
        Returns:
            格式化后的邮箱
        """
        return str(value).strip().lower()
    
    def _parse_duration(self, value: str) -> int:
        """
        解析时长（如 "7天" → 7）
        
        Args:
            value: 时长字符串
            
        Returns:
            天数
        """
        # 提取数字
        match = re.search(r'(\d+)', value)
        if match:
            days = int(match.group(1))
            
            # 检查单位
            if "周" in value or "week" in value.lower():
                return days * 7
            elif "月" in value or "month" in value.lower():
                return days * 30
            elif "年" in value or "year" in value.lower():
                return days * 365
            else:
                return days
        
        return 7  # 默认7天
