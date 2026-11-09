"""
外观发放服务 - 连接 Grafana 后台发放外观到外观中心平台
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

# Grafana 外观管理 API 配置
GRAFANA_APPEARANCE_API = os.getenv(
    "GRAFANA_APPEARANCE_API",
    "https://internal.example.invalid/api/v2/admin/user/appearance/manage"
)

# 默认请求头（从 curl 命令提取的关键头部）
DEFAULT_HEADERS = {
    'accept': 'application/json',
    'accept-language': 'zh-CN,zh;q=0.9',
    'content-type': 'application/json',
    'origin': 'https://internal.example.invalid',
    'referer': 'https://internal.example.invalid/app/grafana/d/EjacH1gnk/uat-yong-hu-wai-guan-pei-zhi-hou-tai?orgId=1',
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
        from .grafana_auth import get_valid_cookies
        return get_valid_cookies()
    except ImportError:
        logger.warning("无法导入grafana_auth模块，请手动配置GRAFANA_COOKIES")
        return ""


def get_appearance_type_from_id(appearance_id: int) -> int:
    """
    根据外观ID开头判断外观类型
    
    Args:
        appearance_id: 外观ID
        
    Returns:
        外观类型数字
    """
    # 转换为字符串获取开头数字
    id_str = str(appearance_id)
    
    if id_str.startswith('1'):
        return 1  # 座驾
    elif id_str.startswith('2'):
        return 2  # 头像框
    elif id_str.startswith('3'):
        return 3  # 名片框
    elif id_str.startswith('4'):
        return 4  # 气泡框
    elif id_str.startswith('5'):
        return 5  # 称号
    elif id_str.startswith('6'):
        return 6  # 挂件
    elif id_str.startswith('7'):
        return 7  # 进场通知
    elif id_str.startswith('8'):
        return 8  # 红包封面
    elif id_str.startswith('9'):
        return 9  # 身份铭牌
    else:
        # 默认返回1（座驾）
        return 1


def parse_duration_to_timestamp(duration_str: str) -> int:
    """
    解析有效期字符串为过期时间戳
    
    Args:
        duration_str: 有效期描述，如"7天"、"30天"、"永久"
        
    Returns:
        过期时间戳（秒）
    """
    current_time = int(time.time())
    
    if duration_str in ["永久", "永久有效"]:
        # 永久有效：设置为当前时间 + 1000天
        return current_time + (1000 * 24 * 60 * 60)
    
    # 解析天数
    if "天" in duration_str:
        try:
            days = int(duration_str.replace("天", "").strip())
            return current_time + (days * 24 * 60 * 60)
        except ValueError:
            pass
    
    # 解析小时
    if "小时" in duration_str or "时" in duration_str:
        try:
            hours = int(duration_str.replace("小时", "").replace("时", "").strip())
            return current_time + (hours * 60 * 60)
        except ValueError:
            pass
    
    # 默认7天
    return current_time + (7 * 24 * 60 * 60)


def issue_appearance_to_platform(
    user_ids: List[int],
    appearance_id: int,
    duration_days: int = 7,
    appearance_type: Optional[int] = None
) -> Dict[str, Any]:
    """
    发放外观到外观中心平台
    
    Args:
        user_ids: 用户ID列表
        appearance_id: 外观ID
        duration_days: 有效期天数，默认7天
        appearance_type: 外观类型，如果不提供则根据ID自动判断
        
    Returns:
        发放结果字典
    """
    # 检查Grafana功能是否启用
    from business_logic.gift.backpack_gift_service import is_grafana_enabled
    if not is_grafana_enabled():
        logger.warning("Grafana功能已禁用，发放外观功能暂不支持")
        return {
            "success": False,
            "message": "⚠️ 发放外观功能暂不支持（Grafana功能已禁用）",
            "data": None
        }
    
    try:
        # 自动判断外观类型
        if appearance_type is None:
            appearance_type = get_appearance_type_from_id(appearance_id)
        
        # 计算过期时间戳
        current_time = int(time.time())
        if duration_days == 1000:  # 永久
            expire_time = current_time + (1000 * 24 * 60 * 60)
            duration_desc = "永久（1000天）"
        else:
            expire_time = current_time + (duration_days * 24 * 60 * 60)
            duration_desc = f"{duration_days}天"
        
        # 准备请求数据
        user_ids_str = ",".join(map(str, user_ids))
        
        payload = {
            "operation": 1,  # 发放操作
            "input_type": 1,  # 输入类型
            "user_ids": user_ids_str,
            "appearance_id": appearance_id,
            "appearance_type": appearance_type,
            "time_type": 1,  # 时间类型
            "expire_time": expire_time,
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
            GRAFANA_APPEARANCE_API,
            json=payload,
            headers=headers,
            cookies=dict(cookie.split('=', 1) for cookie in cookies_str.split('; ') if '=' in cookie),
            timeout=30
        )
        
        # 检查响应
        if response.status_code == 200:
            result_data = response.json()
            
            # 格式化成功消息
            expire_time_str = datetime.fromtimestamp(expire_time).strftime("%Y-%m-%d %H:%M:%S")
            
            message = f"✅ 外观发放成功\n"
            message += f"外观ID：{appearance_id}\n"
            message += f"外观类型：{appearance_type}\n"
            message += f"用户数量：{len(user_ids)}\n"
            message += f"用户ID：{user_ids_str}\n"
            message += f"有效期：{duration_desc}\n"
            message += f"过期时间：{expire_time_str}"
            
            return {
                "success": True,
                "message": message,
                "data": {
                    "appearance_id": appearance_id,
                    "appearance_type": appearance_type,
                    "user_ids": user_ids,
                    "user_count": len(user_ids),
                    "duration_days": duration_days,
                    "expire_time": expire_time,
                    "expire_time_str": expire_time_str,
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
        logger.error(f"发放外观失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 发放外观失败：{str(e)}",
            "data": None
        }


def issue_appearance_single(
    user_id: int,
    appearance_id: int,
    duration_days: int = 7,
    appearance_type: Optional[int] = None
) -> Dict[str, Any]:
    """
    发放外观给单个用户（便捷方法）
    
    Args:
        user_id: 用户ID
        appearance_id: 外观ID
        duration_days: 有效期天数，默认7天
        appearance_type: 外观类型，如果不提供则根据ID自动判断
        
    Returns:
        发放结果字典
    """
    return issue_appearance_to_platform([user_id], appearance_id, duration_days, appearance_type)


def validate_appearance_params(
    user_ids: List[int],
    appearance_id: int,
    duration_days: int
) -> Optional[str]:
    """
    验证外观发放参数
    
    Args:
        user_ids: 用户ID列表
        appearance_id: 外观ID
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
    
    # 验证外观ID
    if not isinstance(appearance_id, int) or appearance_id <= 0:
        return f"无效的外观ID：{appearance_id}"
    
    # 验证有效期
    if not isinstance(duration_days, int) or duration_days < 1 or duration_days > 1000:
        return f"有效期必须在1-1000天之间，当前值：{duration_days}"
    
    return None
