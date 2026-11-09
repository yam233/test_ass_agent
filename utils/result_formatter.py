"""通用结果格式化器"""
from typing import Dict, Any


class ResultFormatter:
    """通用结果格式化器"""
    
    @staticmethod
    def format_success(data: Any, message: str = "Success") -> Dict[str, Any]:
        """
        格式化成功结果
        
        Args:
            data: 数据
            message: 消息
            
        Returns:
            格式化后的结果
        """
        return {
            "success": True,
            "data": data,
            "message": message
        }
    
    @staticmethod
    def format_error(error: str, code: str = "ERROR") -> Dict[str, Any]:
        """
        格式化错误结果
        
        Args:
            error: 错误信息
            code: 错误代码
            
        Returns:
            格式化后的结果
        """
        return {
            "success": False,
            "error": error,
            "code": code
        }


# 企微格式化工具（猫耳测试助手专用）

def format_wechat_card(card_data: Dict[str, Any]) -> str:
    """
    格式化企微卡片
    
    Args:
        card_data: 卡片数据
            - title: 标题
            - color: 颜色（#00C853=绿色成功，#FF5252=红色失败）
            - fields: 字段列表 [{"name": "字段名", "value": "字段值"}]
            
    Returns:
        企微Markdown卡片格式
    """
    title = card_data.get("title", "操作结果")
    color = card_data.get("color", "#00C853")
    fields = card_data.get("fields", [])
    
    # 企微Markdown卡片格式
    card = f"""<div class="card" style="background-color:{color};padding:10px;border-radius:5px;">
<h3 style="color:white;">{title}</h3>
<table style="width:100%;background-color:white;">
"""
    
    for field in fields:
        name = field.get("name", "")
        value = field.get("value", "")
        card += f"""<tr>
<td style="padding:5px;"><b>{name}</b></td>
<td style="padding:5px;">{value}</td>
</tr>"""
    
    card += """</table>
</div>"""
    
    return card


def format_wechat_table(table_data: Dict[str, Any]) -> str:
    """
    格式化企微表格
    
    Args:
        table_data: 表格数据
            - headers: 表头列表
            - rows: 行数据列表
            
    Returns:
        企微Markdown表格格式
    """
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])
    
    if not headers or not rows:
        return "暂无数据"
    
    # Markdown表格格式
    table = f"| {' | '.join(headers)} |\n"
    table += f"| {' | '.join(['---'] * len(headers))} |\n"
    
    for row in rows:
        table += f"| {' | '.join(str(cell) for cell in row)} |\n"
    
    return table


def format_success_card(title: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    格式化成功卡片
    
    Args:
        title: 卡片标题
        data: 数据字典
        
    Returns:
        卡片数据
    """
    fields = []
    for key, value in data.items():
        # 转换键名为中文
        field_name = translate_field_name(key)
        fields.append({"name": field_name, "value": str(value)})
    
    return {
        "title": title,
        "color": "#00C853",  # 绿色
        "fields": fields
    }


def format_error_card(title: str, error_msg: str) -> Dict[str, Any]:
    """
    格式化错误卡片
    
    Args:
        title: 卡片标题
        error_msg: 错误信息
        
    Returns:
        卡片数据
    """
    return {
        "title": title,
        "color": "#FF5252",  # 红色
        "fields": [
            {"name": "失败原因", "value": error_msg}
        ]
    }


def translate_field_name(field_name: str) -> str:
    """
    翻译字段名为中文
    
    Args:
        field_name: 英文字段名
        
    Returns:
        中文字段名
    """
    translations = {
        "gift_id": "礼物ID",
        "user_id": "用户ID",
        "target_id": "目标ID",
        "room_id": "直播间ID",
        "duration_days": "有效期（天）",
        "batch_count": "发放数量",
        "success_count": "成功数量",
        "failed_count": "失败数量",
        "issue_type": "发放类型",
        "record_id": "记录ID",
        "flow_id": "流水号",
        "operator": "操作人",
        "env": "环境",
        "operation_log_id": "操作日志ID",
        "phone": "手机号",
        "email": "邮箱",
        "appearance_id": "外观ID",
        "reward_id": "奖励ID",
        "pool_id": "奖池ID"
    }
    
    return translations.get(field_name, field_name)
