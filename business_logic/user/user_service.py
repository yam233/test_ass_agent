"""
用户信息查询服务
参考 testopsProject 实现，但使用配置驱动，不硬编码
"""
import logging
from typing import Dict, Any, Optional
from business_logic.common import (
    query_user_info as db_query_user_info,
    execute_query,
    query_room_by_user_id
)

logger = logging.getLogger(__name__)


def query_user_info(
    user_id: Optional[int] = None,
    room_id: Optional[int] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None
) -> Dict[str, Any]:
    """
    查询用户信息
    参考 testopsProject 的实现方式
    
    Args:
        user_id: 用户ID
        room_id: 直播间ID
        email: 邮箱
        phone: 手机号
    
    Returns:
        用户信息字典
    """
    try:
        # 如果提供了 room_id，先从MongoDB查询对应的 user_id
        if room_id and not user_id:
            try:
                # 从MongoDB查询直播间信息
                room_info = query_room_by_user_id(room_id)
                if not room_info:
                    # 尝试直接查询room_id
                    from business_logic.common.mongo_db import query_room_info
                    room_data = query_room_info(room_id)
                    if room_data:
                        user_id = room_data.get('creator_id')
                    else:
                        return {
                            "success": False,
                            "message": f"直播间 {room_id} 不存在"
                        }
                else:
                    user_id = room_info.get('creator_id')
            except Exception as e:
                logger.warning(f"查询直播间失败: {e}")
                return {
                    "success": False,
                    "message": f"查询直播间失败: {str(e)}"
                }
        
        # 确定查询值
        query_value = None
        if user_id:
            query_value = str(user_id)
        elif email:
            query_value = email
        elif phone:
            query_value = phone
        else:
            return {
                "success": False,
                "message": "必须提供 user_id、room_id、email 或 phone 中的至少一个参数"
            }
        
        # 查询用户信息
        user = db_query_user_info(query_value)
        
        if not user:
            # 根据查询类型提供不同的提示
            if user_id:
                message = f"❌ 用户 {user_id} 不存在\n\n💡 建议：\n  • 检查用户ID是否正确\n  • 如果这是手机号，请使用：查询手机号{user_id}的用户信息\n  • 尝试使用邮箱查询"
            elif phone:
                message = f"❌ 手机号 {phone} 未注册\n\n💡 建议：\n  • 检查手机号是否正确（需包含完整号码）\n  • 尝试使用用户ID查询"
            elif email:
                message = f"❌ 邮箱 {email} 未注册\n\n💡 建议：\n  • 检查邮箱是否正确\n  • 尝试使用用户ID或手机号查询"
            else:
                message = "❌ 用户不存在\n\n💡 建议：\n  • 检查查询条件是否正确\n  • 尝试使用其他方式查询（用户ID、手机号、邮箱）"
            
            return {
                "success": False,
                "message": message
            }
        
        # 查询直播间信息（从 MongoDB）
        room_info = None
        try:
            room_data = query_room_by_user_id(user['id'])
            if room_data:
                room_info = {
                    'id': room_data.get('room_id'),
                    'name': room_data.get('name')
                }
        except Exception as e:
            logger.warning(f"查询直播间信息失败: {e}")
        
        # 格式化返回数据
        return format_user_info(user, room_info)
            
    except Exception as e:
        logger.error(f"查询用户信息失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"查询失败: {str(e)}"
        }


def format_user_info(user: Dict[str, Any], room_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    格式化用户信息
    
    Args:
        user: 用户数据
        room_info: 直播间数据
    
    Returns:
        格式化后的用户信息
    """
    # 格式化手机号（带区号）
    phone_display = None
    if user.get('mobile'):
        region = user.get('region', 86)
        phone_display = f"+{region} {user['mobile']}"
    
    return {
        "success": True,
        "data": {
            "user_id": user['id'],
            "username": user['username'],
            "phone": phone_display,
            "email": user.get('email'),
            "room_id": room_info['id'] if room_info else None,
            "room_name": room_info['name'] if room_info else None,
            "created_at": user.get('ctime'),
            "icon_url": user.get('iconurl')
        },
        "message": "查询成功"
    }
