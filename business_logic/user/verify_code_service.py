"""
验证码查询服务
参考 MaoerProject 实现，支持直接连接 Redis
"""
import os
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from utils.redis_client import wrap_safe_redis_client

logger = logging.getLogger(__name__)
load_dotenv()

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis 库未安装，验证码查询功能将不可用")


def get_redis_config() -> Dict[str, Any]:
    """
    获取 Redis 配置（从环境变量）
    
    Returns:
        Redis 配置字典
    """
    password = os.getenv('REDIS_PASSWORD', '')
    # 如果密码包含冒号，说明是 username:password 格式
    if ':' in password:
        return {
            "host": os.getenv('REDIS_HOST'),
            "port": int(os.getenv('REDIS_PORT', 6379)),
            "password": password,  # Redis 6+ 支持 username:password 格式
            "db": int(os.getenv('REDIS_DB', 0))
        }
    else:
        return {
            "host": os.getenv('REDIS_HOST'),
            "port": int(os.getenv('REDIS_PORT', 6379)),
            "password": password or None,
            "db": int(os.getenv('REDIS_DB', 0))
        }


def query_verify_code(
    phone: Optional[str] = None,
    user_id: Optional[int] = None,
    email: Optional[str] = None
) -> Dict[str, Any]:
    """
    查询验证码
    参考 MaoerProject 的实现方式
    
    Args:
        phone: 手机号
        user_id: 用户ID
        email: 邮箱
    
    Returns:
        验证码信息字典
    """
    # 确定查询标识符
    identifier = phone or email
    is_email = bool(email)
    
    if not identifier and user_id:
        # 如果只提供了 user_id，需要先查询手机号或邮箱
        from .user_service import query_user_info
        user_info = query_user_info(user_id=user_id)
        if user_info.get('success'):
            phone_str = user_info['data'].get('phone', '')
            if phone_str and '+' in phone_str:
                # 提取手机号（去掉区号）
                identifier = phone_str.split(' ')[-1]
            elif user_info['data'].get('email'):
                identifier = user_info['data']['email']
                is_email = True
    
    if not identifier:
        return {
            "success": False,
            "message": "❌ 缺少查询参数\n\n请提供用户ID、手机号或邮箱中的至少一个。例如：\n• 查询用户9075566的验证码\n• 查询手机号15000000490的验证码\n• 查询邮箱live@missevan.cn的验证码"
        }
    
    # 查询验证码
    return query_verify_code_direct_redis(identifier, is_email)


def query_verify_code_direct_redis(identifier: str, is_email: bool = False) -> Dict[str, Any]:
    """
    直接连接 Redis 查询验证码
    参考 MaoerProject 的实现
    
    Args:
        identifier: 手机号或邮箱
        is_email: 是否为邮箱
    
    Returns:
        查询结果字典
    """
    result = {
        "mobile" if not is_email else "email": identifier,
        "verify_code": None,
        "ttl": None,
        "has_interval": False,
        "has_lock": False,
        "method": "direct_redis"
    }
    
    # 检查 Redis 配置
    redis_config = get_redis_config()
    if not redis_config.get("host"):
        return {
            "success": False,
            "message": "Redis 配置未设置，无法查询验证码"
        }
    
    if not REDIS_AVAILABLE:
        return {
            "success": False,
            "message": "redis 库未安装，请运行: pip install redis"
        }
    
    try:
        # 连接 Redis
        raw_client = redis.Redis(
            host=redis_config.get("host"),
            port=redis_config.get("port", 6379),
            password=redis_config.get("password") or None,
            db=redis_config.get("db", 0),
            decode_responses=True,
            socket_connect_timeout=5
        )
        r = wrap_safe_redis_client(raw_client)
        
        # 测试连接
        r.ping()
        
        # 查询验证码（key 格式：vcode:account:{identifier}）
        vcode_key = f"vcode:account:{identifier}"
        verify_code = r.get(vcode_key)
        
        if verify_code:
            result["verify_code"] = verify_code
            
            # 查询 TTL
            ttl = r.ttl(vcode_key)
            if ttl > 0:
                result["ttl"] = ttl
            
            # 查询间隔限制
            interval_key = f"vcode:account:{identifier}:interval"
            result["has_interval"] = r.exists(interval_key) > 0
            
            # 查询锁状态
            lock_key = f"lock_vcode:account:{identifier}lock"
            result["has_lock"] = r.exists(lock_key) > 0
        
        r.close()
        
        return format_verify_code(result)
        
    except redis.ConnectionError as e:
        logger.error(f"Redis 连接失败: {e}")
        return {
            "success": False,
            "message": f"Redis 连接失败: {str(e)}"
        }
    except Exception as e:
        logger.error(f"查询验证码失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"查询失败: {str(e)}"
        }


def format_verify_code(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    格式化验证码查询结果
    
    Args:
        result: 原始查询结果
    
    Returns:
        格式化后的结果
    """
    identifier = result.get("mobile") or result.get("email")
    
    if result.get("verify_code"):
        return {
            "success": True,
            "data": {
                "identifier": identifier,
                "verify_code": result["verify_code"],
                "ttl": result.get("ttl"),
                "has_interval": result.get("has_interval", False),
                "has_lock": result.get("has_lock", False)
            },
            "message": f"✅ 查询成功\n验证码: {result['verify_code']}\n有效期: {result.get('ttl', 'N/A')}秒"
        }
    else:
        # 未找到验证码也返回 success=True，但数据为空
        # 这是正常的业务结果，不是错误
        return {
            "success": True,
            "data": {
                "identifier": identifier,
                "verify_code": None,
                "found": False
            },
            "message": f"ℹ️  未找到验证码\n\n可能原因：\n• 该用户最近没有请求过验证码\n• 验证码已过期（有效期5分钟）\n• 标识符不正确"
        }
