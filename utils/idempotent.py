"""
幂等性保护工具

⚠️ 重要变更：Redis已禁用，仅使用内存缓存

提供基于请求ID的幂等性保护，防止重复执行。

设计原则：
1. 客户端生成唯一请求ID（request_id）
2. 服务端检查请求ID是否已执行
3. 如果已执行，返回缓存结果
4. 如果未执行，执行并缓存结果

适用场景：
- 执行类操作（礼物发放、钻石充值、脚本执行等）
- 防止网络重试导致的重复执行
- 防止用户误操作导致的重复执行

缓存特性：
- ✅ 使用内存缓存（单机场景）
- ❌ Redis缓存已禁用
- 服务重启后幂等性缓存会清空
- 不支持跨进程/跨服务器的幂等性保护

Redis使用限制：
- Redis仅用于查询验证码
- 幂等性缓存不使用Redis
- 禁止任何Redis删除操作
"""
import json
import time
import hashlib
import logging
from typing import Optional, Dict, Any, Callable
from functools import wraps

logger = logging.getLogger(__name__)

class IdempotentCache:
    """
    幂等性缓存（仅使用内存缓存，不使用Redis）
    
    支持内存缓存，Redis已禁用
    """
    
    def __init__(
        self, 
        ttl: int = 300,  # 5分钟
        use_redis: bool = False,
        redis_client=None
    ):
        """
        初始化幂等性缓存（仅使用内存缓存，Redis已禁用）
        
        Args:
            ttl: 缓存过期时间（秒），默认 5 分钟
            use_redis: 是否使用 Redis（已禁用，保留参数仅为兼容性）
            redis_client: Redis 客户端实例（已禁用，保留参数仅为兼容性）
        """
        self.ttl = ttl
        # 强制禁用Redis
        self.use_redis = False
        self.redis_client = None
        
        # 内存缓存（单机场景）
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        
        logger.info(
            f"✓ 幂等性缓存已初始化 "
            f"(ttl={ttl}s, Redis已禁用，仅使用内存缓存)"
        )
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        获取缓存结果（仅从内存缓存获取，Redis已禁用）
        
        Args:
            key: 幂等键
            
        Returns:
            缓存的结果，如果不存在或已过期则返回 None
        """
        # 仅使用内存缓存（Redis已禁用）
        if key in self.memory_cache:
            cache_data = self.memory_cache[key]
            if time.time() - cache_data["timestamp"] < self.ttl:
                return cache_data["result"]
            else:
                # 过期，删除
                del self.memory_cache[key]
        
        return None
    
    def set(self, key: str, result: Dict[str, Any]):
        """
        设置缓存结果
        
        Args:
            key: 幂等键
            result: 执行结果
        """
        # 仅使用内存缓存（Redis已禁用）
        self.memory_cache[key] = {
            "timestamp": time.time(),
            "result": result
        }
        
        # 清理过期缓存（简单版，每次设置时清理）
        self._cleanup_expired()
    
    def _cleanup_expired(self):
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = [
            k for k, v in self.memory_cache.items()
            if current_time - v["timestamp"] > self.ttl
        ]
        for k in expired_keys:
            del self.memory_cache[k]
    
    # clear 方法已移除，避免误操作缓存


# 全局幂等性缓存实例
_idempotent_cache: Optional[IdempotentCache] = None


def get_idempotent_cache() -> IdempotentCache:
    """
    获取全局幂等性缓存实例
    
    Returns:
        幂等性缓存实例
    """
    global _idempotent_cache
    if _idempotent_cache is None:
        # 尝试获取 Redis 客户端
        redis_client = None
        use_redis = False
        
        try:
            from utils.redis_client import get_redis_client
            redis_client = get_redis_client()
            
            if redis_client is not None:
                use_redis = True
                logger.info("✓ 幂等性缓存将使用内存缓存（Redis已禁用）")
        except Exception as e:
            logger.warning(f"初始化失败: {e}，使用内存缓存")
        
        # 强制禁用Redis
        _idempotent_cache = IdempotentCache(
            ttl=300,  # 5分钟
            use_redis=False,
            redis_client=None
        )
    return _idempotent_cache


def generate_idempotent_key(
    request_id: Optional[str] = None,
    business_code: Optional[str] = None,
    skill_name: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    operator: Optional[str] = None
) -> Optional[str]:
    """
    生成幂等键
    
    优先级：
    1. 如果提供了 request_id，直接使用
    2. 否则，根据 business_code + skill_name + params + operator 生成
    
    Args:
        request_id: 请求ID（客户端生成）
        business_code: 业务代码
        skill_name: Skill 名称
        params: 参数字典
        operator: 操作人
        
    Returns:
        幂等键，如果无法生成则返回 None
    """
    # 优先使用 request_id
    if request_id:
        return f"idempotent:request:{request_id}"
    
    # 根据业务参数生成
    if business_code and skill_name and params:
        # 只对执行类操作生成幂等键
        execute_skills = [
            "execute_gift_issue",
            "add_backpack_gift",
            "add_user_gift",
            "add_room_gift",
            "delete_gift_record",
            "top_up_diamond",
            "run_script",
            "update_pool_gift_weight_to_max",
            "update_pool_ssr_weight_to_zero"
        ]
        
        if skill_name not in execute_skills:
            return None  # 查询类操作不需要幂等
        
        # 生成幂等键
        key_data = {
            "business_code": business_code,
            "skill_name": skill_name,
            "params": params,
            "operator": operator or "unknown"
        }
        key_str = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        return f"idempotent:skill:{business_code}:{skill_name}:{key_hash}"
    
    return None


def check_idempotent(
    request_id: Optional[str] = None,
    business_code: Optional[str] = None,
    skill_name: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    operator: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    检查是否已执行（幂等性检查）
    
    Args:
        request_id: 请求ID
        business_code: 业务代码
        skill_name: Skill 名称
        params: 参数字典
        operator: 操作人
        
    Returns:
        如果已执行，返回缓存的结果；否则返回 None
    """
    key = generate_idempotent_key(
        request_id=request_id,
        business_code=business_code,
        skill_name=skill_name,
        params=params,
        operator=operator
    )
    
    if not key:
        return None  # 不需要幂等性检查
    
    cache = get_idempotent_cache()
    cached_result = cache.get(key)
    
    if cached_result:
        logger.info(f"幂等性检查命中: {key[:50]}...")
        return cached_result
    
    return None


def save_idempotent_result(
    result: Dict[str, Any],
    request_id: Optional[str] = None,
    business_code: Optional[str] = None,
    skill_name: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    operator: Optional[str] = None
):
    """
    保存执行结果（用于幂等性）
    
    Args:
        result: 执行结果
        request_id: 请求ID
        business_code: 业务代码
        skill_name: Skill 名称
        params: 参数字典
        operator: 操作人
    """
    key = generate_idempotent_key(
        request_id=request_id,
        business_code=business_code,
        skill_name=skill_name,
        params=params,
        operator=operator
    )
    
    if not key:
        return  # 不需要保存
    
    cache = get_idempotent_cache()
    cache.set(key, result)
    
    logger.debug(f"幂等性结果已保存: {key[:50]}...")


def idempotent(key_func: Callable):
    """
    幂等性装饰器
    
    Args:
        key_func: 生成幂等键的函数
        
    Returns:
        装饰器函数
        
    Example:
        @idempotent(lambda skill_input: generate_idempotent_key(
            business_code=skill_input.business_code,
            skill_name=skill_input.skill_name,
            params=skill_input.params,
            operator=skill_input.operator
        ))
        async def execute(self, skill_input):
            pass
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成幂等键
            key = key_func(*args, **kwargs)
            
            if not key:
                # 不需要幂等性检查
                return await func(*args, **kwargs)
            
            # 检查是否已执行
            cache = get_idempotent_cache()
            cached_result = cache.get(key)
            
            if cached_result:
                logger.info(f"幂等性检查命中，返回缓存结果: {key[:50]}...")
                return cached_result
            
            # 执行并缓存结果
            result = await func(*args, **kwargs)
            cache.set(key, result)
            
            return result
        
        return wrapper
    return decorator


# 便捷函数
# clear_idempotent_cache 函数已移除，避免误操作缓存
