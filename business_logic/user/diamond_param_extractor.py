"""
钻石充值参数提取器
支持自动识别和转换"万"、"百万"、"千万"、"亿"等单位
"""
import re
from typing import Optional, Tuple


def extract_diamond_amount(user_input: str) -> Optional[int]:
    """
    从用户输入中提取钻石数量（单位：万）
    
    支持的格式：
    - 100万、200万 -> 100、200
    - 1千万、2千万 -> 1000、2000
    - 1亿、2亿 -> 10000、20000
    - 100 -> 100（默认为万）
    
    Args:
        user_input: 用户输入文本
        
    Returns:
        钻石数量（万为单位），如果无法提取则返回None
    """
    # 移除空格
    text = user_input.replace(" ", "").replace("　", "")
    
    # 匹配模式（按优先级排序）
    patterns = [
        # 亿：1亿 -> 10000万
        (r'(\d+(?:\.\d+)?)\s*亿', lambda x: int(float(x) * 10000)),
        # 千万：1千万 -> 1000万
        (r'(\d+(?:\.\d+)?)\s*千万', lambda x: int(float(x) * 1000)),
        # 百万：1百万 -> 100万
        (r'(\d+(?:\.\d+)?)\s*百万', lambda x: int(float(x) * 100)),
        # 万：100万 -> 100万
        (r'(\d+(?:\.\d+)?)\s*万', lambda x: int(float(x))),
    ]
    
    for pattern, converter in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1)
            return converter(value)
    
    # 如果没有单位，尝试提取纯数字（假设为万）
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match:
        return int(float(match.group(1)))
    
    return None


def convert_to_diamond_100w_units(diamond_wan: int) -> int:
    """
    将万单位转换为100万单位
    
    Args:
        diamond_wan: 钻石数量（万为单位）
        
    Returns:
        钻石数量（100万为单位）
    """
    return diamond_wan // 100


def extract_diamond_100w_units(user_input: str) -> Tuple[Optional[int], Optional[int]]:
    """
    从用户输入中提取钻石数量，返回两种单位
    
    Args:
        user_input: 用户输入文本
        
    Returns:
        (万单位, 100万单位) 的元组，如果无法提取则返回(None, None)
    """
    diamond_wan = extract_diamond_amount(user_input)
    if diamond_wan is None:
        return None, None
    
    diamond_100w_units = convert_to_diamond_100w_units(diamond_wan)
    return diamond_wan, diamond_100w_units


if __name__ == "__main__":
    # 测试
    test_cases = [
        "给用户9075566发100万钻石",
        "给用户9075566充值200万钻石",
        "用户9075566充值5个100万单位钻石",
        "给用户9075566发1亿钻石",
        "给用户9075566充值3千万钻石",
        "给用户9075566发500万钻石",
        "充值1000万",
        "充值2亿",
    ]
    
    print("钻石数量提取测试")
    print("=" * 80)
    for test in test_cases:
        wan, units = extract_diamond_100w_units(test)
        print(f"输入: {test}")
        print(f"  -> {wan}万 = {units}个100万单位")
        print()
