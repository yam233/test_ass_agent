"""
背包礼物发放服务 - 连接 Grafana 后台发放背包礼物
"""
import time
import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

# Grafana 背包礼物发放 API 配置
GRAFANA_GIVEGIFT_API = os.getenv(
    "GRAFANA_GIVEGIFT_API",
    "https://internal.example.invalid/api/v2/admin/user/givegift"
)
GRAFANA_CLEARGIFT_API = os.getenv(
    "GRAFANA_CLEARGIFT_API",
    "https://internal.example.invalid/api/v2/admin/user/cleargift"
)

# 默认请求头（从 curl 命令提取的关键头部）
DEFAULT_HEADERS = {
    'accept': 'application/json',
    'accept-language': 'zh-CN,zh;q=0.9',
    'content-type': 'application/json',
    'origin': 'https://internal.example.invalid',
    'referer': 'https://internal.example.invalid/app/grafana/d/QSk7N1LMk/uat-bei-bao-li-wu-guan-li?orgId=1',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
}

# Cookie 配置（从环境变量读取，避免硬编码敏感信息）
def get_grafana_cookies() -> str:
    """获取 Grafana 认证 Cookie（带缓存和有效性检查）"""
    # 首先尝试从环境变量读取
    cookies_from_env = os.getenv('GRAFANA_COOKIES', '').strip()
    if cookies_from_env:
        return cookies_from_env
    
    # 如果环境变量没有Cookie，使用智能Cookie获取
    try:
        from business_logic.appearance.grafana_auth import get_valid_cookies
        return get_valid_cookies()
    except ImportError:
        logger.warning("无法导入grafana_auth模块，请手动配置GRAFANA_COOKIES")
        return ""


def is_grafana_enabled() -> bool:
    """检查Grafana功能是否启用"""
    try:
        from business_logic.appearance.grafana_auth import is_grafana_enabled as check_enabled
        return check_enabled()
    except ImportError:
        # 如果无法导入，默认启用
        return True


def is_grafana_fallback_enabled() -> bool:
    """检查Grafana回退功能是否启用"""
    try:
        from business_logic.appearance.grafana_auth import is_grafana_fallback_enabled as check_fallback
        return check_fallback()
    except ImportError:
        # 如果无法导入，默认启用回退
        return True


def _fallback_to_db_insert(user_ids: List[int], gift_id: int, num: int, duration_days: int, reason: str = "Grafana失败") -> Dict[str, Any]:
    """
    回退到DB方式插入背包礼物
    
    Args:
        user_ids: 用户ID列表
        gift_id: 礼物ID
        num: 数量
        duration_days: 有效期天数
        reason: 回退原因
        
    Returns:
        发放结果字典
    """
    try:
        from business_logic.common.mongo_db import insert_user_item
        results = []
        for user_id in user_ids:
            try:
                item_id = insert_user_item(user_id, gift_id, num, duration_days)
                results.append({"user_id": user_id, "success": True, "item_id": item_id})
            except Exception as e:
                results.append({"user_id": user_id, "success": False, "error": str(e)})
        
        success_count = sum(1 for r in results if r["success"])
        fail_count = len(results) - success_count
        
        return {
            "success": success_count > 0,
            "message": f"✅ 背包礼物发放成功（{reason}，已回退到DB）\n用户：{','.join(map(str, user_ids))}\n礼物ID：{gift_id}\n数量：{num}\n有效期：{duration_days}天\n结果：成功 {success_count} / 总计 {len(results)}",
            "data": {
                "success_count": success_count,
                "fail_count": fail_count,
                "total": len(results),
                "route": "db_fallback",
                "gift_id": gift_id,
                "num": num,
                "duration_days": duration_days,
                "user_ids": user_ids
            }
        }
    except Exception as e:
        logger.error(f"DB回退失败: {e}")
        return {
            "success": False,
            "message": f"❌ {reason}，DB回退也失败：{str(e)}",
            "data": None
        }


def calculate_end_time(duration_days: int) -> int:
    """
    计算过期时间戳
    
    Args:
        duration_days: 有效期天数
        
    Returns:
        过期时间戳（秒）
    """
    current_time = int(time.time())
    
    if duration_days == 1000:  # 永久
        return current_time + (1000 * 24 * 60 * 60)
    else:
        return current_time + (duration_days * 24 * 60 * 60)


def issue_backpack_gift_via_grafana(
    user_ids: List[int],
    gift_id: int,
    num: int = 1,
    duration_days: int = 7
) -> Dict[str, Any]:
    """
    通过 Grafana 后台发放背包礼物
    
    Args:
        user_ids: 用户ID列表
        gift_id: 礼物ID
        num: 数量，默认1
        duration_days: 有效期天数，默认7天
        
    Returns:
        发放结果字典
    """
    # 检查Grafana功能是否启用
    if not is_grafana_enabled():
        logger.warning("Grafana功能已禁用")
        if not is_grafana_fallback_enabled():
            return {
                "success": False,
                "message": "❌ Grafana功能已禁用且未启用回退机制",
                "data": None
            }
        # 如果启用回退，尝试使用DB方式
        logger.info("Grafana已禁用，尝试使用DB方式发放")
        return _fallback_to_db_insert(user_ids, gift_id, num, duration_days, "Grafana已禁用")
    
    try:
        # 计算过期时间戳
        end_time = calculate_end_time(duration_days)
        
        # 准备请求数据
        user_ids_str = ",".join(map(str, user_ids))
        
        payload = {
            "type": 1,  # 背包礼物类型
            "gift_id": gift_id,
            "user_ids": user_ids_str,
            "num": num,
            "end_time": end_time,
            "confirm": 1  # 确认发放
        }
        
        # 准备请求头
        headers = DEFAULT_HEADERS.copy()
        
        # 获取 Cookie
        cookies_str = get_grafana_cookies()
        if not cookies_str:
            return {
                "success": False,
                "message": "❌ 缺少 Grafana 认证信息，请配置 GRAFANA_COOKIES 环境变量",
                "data": None
            }
        
        # 发送请求
        response = requests.post(
            GRAFANA_GIVEGIFT_API,
            json=payload,
            headers=headers,
            cookies=dict(cookie.split('=', 1) for cookie in cookies_str.split('; ') if '=' in cookie),
            timeout=30
        )
        
        # 检查响应
        if response.status_code == 200:
            result_data = response.json()
            
            # 格式化成功消息
            duration_desc = "永久（1000天）" if duration_days == 1000 else f"{duration_days}天"
            end_time_str = datetime.fromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S")
            
            message = f"✅ 背包礼物发放成功\n"
            message += f"礼物ID：{gift_id}\n"
            message += f"用户数量：{len(user_ids)}\n"
            message += f"用户ID：{user_ids_str}\n"
            message += f"数量：{num}\n"
            message += f"有效期：{duration_desc}\n"
            message += f"过期时间：{end_time_str}"
            
            return {
                "success": True,
                "message": message,
                "data": {
                    "gift_id": gift_id,
                    "user_ids": user_ids,
                    "user_count": len(user_ids),
                    "num": num,
                    "duration_days": duration_days,
                    "end_time": end_time,
                    "end_time_str": end_time_str,
                    "api_response": result_data
                }
            }
        else:
            error_msg = f"API 请求失败，状态码：{response.status_code}"
            try:
                error_data = response.json()
                if "message" in error_data:
                    error_msg += f"，错误信息：{error_data['message']}"
            except:
                error_msg += f"，响应内容：{response.text[:200]}"
            
            return {
                "success": False,
                "message": f"❌ {error_msg}",
                "data": {
                    "status_code": response.status_code,
                    "response_text": response.text[:500]
                }
            }
            
    except requests.exceptions.Timeout as e:
        logger.warning(f"Grafana请求超时: {e}")
        if is_grafana_fallback_enabled():
            logger.info("Grafana超时，尝试使用DB方式发放")
            return _fallback_to_db_insert(user_ids, gift_id, num, duration_days, "Grafana请求超时")
        return {
            "success": False,
            "message": "❌ 请求超时，请检查网络连接或稍后重试",
            "data": None
        }
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"Grafana连接失败: {e}")
        if is_grafana_fallback_enabled():
            logger.info("Grafana连接失败，尝试使用DB方式发放")
            return _fallback_to_db_insert(user_ids, gift_id, num, duration_days, "Grafana连接失败")
        return {
            "success": False,
            "message": "❌ 连接失败，请检查网络连接或 API 地址",
            "data": None
        }
    except Exception as e:
        logger.error(f"发放背包礼物失败: {e}", exc_info=True)
        if is_grafana_fallback_enabled():
            logger.info("Grafana异常，尝试使用DB方式发放")
            return _fallback_to_db_insert(user_ids, gift_id, num, duration_days, f"Grafana异常: {str(e)}")
        return {
            "success": False,
            "message": f"❌ 发放背包礼物失败：{str(e)}",
            "data": None
        }


def issue_backpack_gift_single(
    user_id: int,
    gift_id: int,
    num: int = 1,
    duration_days: int = 7
) -> Dict[str, Any]:
    """
    发放背包礼物给单个用户（便捷方法）
    
    Args:
        user_id: 用户ID
        gift_id: 礼物ID
        num: 数量，默认1
        duration_days: 有效期天数，默认7天
        
    Returns:
        发放结果字典
    """
    return issue_backpack_gift_via_grafana([user_id], gift_id, num, duration_days)


def validate_backpack_gift_params(
    user_ids: List[int],
    gift_id: int,
    num: int,
    duration_days: int
) -> Optional[str]:
    """
    验证背包礼物发放参数
    
    Args:
        user_ids: 用户ID列表
        gift_id: 礼物ID
        num: 数量
        duration_days: 有效期天数
        
    Returns:
        错误信息，如果验证通过返回None
    """
    # 验证用户ID
    if not user_ids:
        return "用户ID列表不能为空"
    
    for user_id in user_ids:
        if not isinstance(user_id, int) or user_id <= 0:
            return f"无效的用户ID：{user_id}"
    
    # 验证礼物ID
    if not isinstance(gift_id, int) or gift_id <= 0:
        return f"无效的礼物ID：{gift_id}"
    
    # 验证数量
    if not isinstance(num, int) or num < 1 or num > 1000:
        return f"数量必须在1-1000之间，当前值：{num}"
    
    # 验证有效期
    if not isinstance(duration_days, int) or duration_days < 1 or duration_days > 1000:
        return f"有效期必须在1-1000天之间，当前值：{duration_days}"
    
    return None


def is_backpack_gift(gift_id: int) -> bool:
    """
    判断礼物ID是否为可通过 Grafana 发放的背包礼物（仅3开头）
    
    Args:
        gift_id: 礼物ID
        
    Returns:
        是否为背包礼物
    """
    gift_id_str = str(gift_id)
    return gift_id_str.startswith('3')


def get_gift_type_name(gift_id: int) -> str:
    """
    根据礼物ID获取礼物类型名称
    
    Args:
        gift_id: 礼物ID
        
    Returns:
        礼物类型名称
    """
    gift_id_str = str(gift_id)
    
    if gift_id_str.startswith('1'):
        return "常规礼物"
    elif gift_id_str.startswith('2'):
        return "用户专属礼物"
    elif gift_id_str.startswith('3'):
        return "免费礼物"
    elif gift_id_str.startswith('4'):
        return "白给礼物"
    elif gift_id_str.startswith('5'):
        return "粉丝礼物"
    elif gift_id_str.startswith('6'):
        return "贵族礼物"
    elif gift_id_str.startswith('7'):
        return "直播间专属礼物"
    elif gift_id_str.startswith('8'):
        return "随机礼物"
    elif gift_id_str.startswith('9'):
        return "奖池礼物"
    else:
        return f"未知类型礼物（{gift_id_str[0]}开头）"


def is_free_gift(gift_id: int) -> bool:
    """
    判断礼物ID是否为免费礼物（3开头）
    
    Args:
        gift_id: 礼物ID
        
    Returns:
        是否为免费礼物
    """
    gift_id_str = str(gift_id)
    return gift_id_str.startswith('3')


def clear_backpack_gift_via_grafana(
    user_ids: List[int],
    gift_id: int
) -> Dict[str, Any]:
    """
    通过 Grafana 后台清空背包礼物
    
    Args:
        user_ids: 用户ID列表
        gift_id: 礼物ID（必须是3开头的免费礼物）
        
    Returns:
        清空结果字典
    """
    # 检查Grafana功能是否启用
    if not is_grafana_enabled():
        logger.warning("Grafana功能已禁用，清空背包礼物功能暂不支持")
        return {
            "success": False,
            "message": "⚠️ 清空背包礼物功能暂不支持（Grafana功能已禁用）",
            "data": None
        }
    
    try:
        # 验证礼物类型（必须是免费礼物）
        if not is_free_gift(gift_id):
            gift_type_name = get_gift_type_name(gift_id)
            return {
                "success": False,
                "message": f"❌ 礼物ID {gift_id} 是{gift_type_name}，不支持清空操作\n\n💡 只有免费礼物（3开头）支持清空背包功能",
                "data": None
            }
        
        # 准备请求数据
        user_ids_str = ",".join(map(str, user_ids))
        
        payload = {
            "type": 1,  # 默认类型
            "gift_id": gift_id,
            "user_ids": user_ids_str
        }
        
        # 准备请求头
        headers = DEFAULT_HEADERS.copy()
        
        # 获取 Cookie
        cookies_str = get_grafana_cookies()
        if not cookies_str:
            return {
                "success": False,
                "message": "❌ 缺少 Grafana 认证信息，请配置 GRAFANA_COOKIES 环境变量",
                "data": None
            }
        
        # 发送请求到清空接口
        response = requests.post(
            GRAFANA_CLEARGIFT_API,
            json=payload,
            headers=headers,
            cookies=dict(cookie.split('=', 1) for cookie in cookies_str.split('; ') if '=' in cookie),
            timeout=30
        )
        
        # 检查响应
        if response.status_code == 200:
            result_data = response.json()
            
            # 格式化成功消息
            message = f"✅ 背包礼物清空成功\n"
            message += f"礼物ID：{gift_id}\n"
            message += f"用户数量：{len(user_ids)}\n"
            message += f"用户ID：{user_ids_str}\n"
            message += f"操作：清空背包中的免费礼物"
            
            return {
                "success": True,
                "message": message,
                "data": {
                    "gift_id": gift_id,
                    "user_ids": user_ids,
                    "user_count": len(user_ids),
                    "operation": "clear",
                    "api_response": result_data
                }
            }
        else:
            error_msg = f"API 请求失败，状态码：{response.status_code}"
            try:
                error_data = response.json()
                if "message" in error_data:
                    error_msg += f"，错误信息：{error_data['message']}"
            except:
                error_msg += f"，响应内容：{response.text[:200]}"
            
            return {
                "success": False,
                "message": f"❌ {error_msg}",
                "data": {
                    "status_code": response.status_code,
                    "response_text": response.text[:500]
                }
            }
            
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "❌ 请求超时，请检查网络连接或稍后重试",
            "data": None
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "message": "❌ 连接失败，请检查网络连接或 API 地址",
            "data": None
        }
    except Exception as e:
        logger.error(f"清空背包礼物失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 清空背包礼物失败：{str(e)}",
            "data": None
        }


def clear_backpack_gift_single(
    user_id: int,
    gift_id: int
) -> Dict[str, Any]:
    """
    清空单个用户的背包礼物（便捷方法）
    
    Args:
        user_id: 用户ID
        gift_id: 礼物ID（必须是3开头的免费礼物）
        
    Returns:
        清空结果字典
    """
    return clear_backpack_gift_via_grafana([user_id], gift_id)


def validate_clear_gift_params(
    user_ids: List[int],
    gift_id: int
) -> Optional[str]:
    """
    验证清空背包礼物参数
    
    Args:
        user_ids: 用户ID列表
        gift_id: 礼物ID
        
    Returns:
        错误信息，如果验证通过返回None
    """
    # 验证用户ID
    if not user_ids:
        return "用户ID列表不能为空"
    
    for user_id in user_ids:
        if not isinstance(user_id, int) or user_id <= 0:
            return f"无效的用户ID：{user_id}"
    
    # 验证礼物ID
    if not isinstance(gift_id, int) or gift_id <= 0:
        return f"无效的礼物ID：{gift_id}"
    
    # 验证礼物类型（必须是免费礼物）
    if not is_free_gift(gift_id):
        gift_type_name = get_gift_type_name(gift_id)
        return f"礼物ID {gift_id} 是{gift_type_name}，只有免费礼物（3开头）支持清空操作"
    
    return None
