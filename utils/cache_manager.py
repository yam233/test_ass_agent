"""
缓存管理器

⚠️ 重要变更：Redis已禁用，仅使用内存缓存

支持的缓存策略：
1. ✅ 内存缓存（LRU）- 当前使用
2. ❌ Redis 缓存 - 已禁用
3. ❌ 多级缓存（内存 + Redis）- 已禁用

使用场景：
- LLM 响应缓存（相同输入返回缓存结果）
- 配置缓存（减少文件读取）
- 意图识别缓存（加速匹配）

缓存特性：
- 服务重启后缓存会清空（内存缓存）
- 不支持跨进程共享缓存
- 不会操作Redis数据库

Redis使用限制：
- Redis仅用于查询验证码（verify_code_service.py）
- 缓存功能不使用Redis
- 禁止任何Redis删除操作
"""
from typing import Any, Optional, Callable
from functools import wraps, lru_cache
import hashlib
import json
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, redis_client=None, default_ttl: int = 3600):
        """
        初始化缓存管理器（仅使用内存缓存，不使用Redis）
        
        Args:
            redis_client: Redis 客户端（已禁用，保留参数仅为兼容性）
            default_ttl: 默认过期时间（秒）
        """
        # 强制禁用Redis，仅使用内存缓存
        self.redis_client = None
        self.default_ttl = default_ttl
        self.memory_cache = {}
        self.cache_stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0
        }
        logger.info("✓ CacheManager 初始化完成（仅使用内存缓存，Redis已禁用）")
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """
        生成缓存键
        
        Args:
            prefix: 键前缀
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            缓存键
        """
        # 将参数序列化为字符串
        key_parts = [prefix]
        
        for arg in args:
            if isinstance(arg, (dict, list)):
                key_parts.append(json.dumps(arg, sort_keys=True))
            else:
                key_parts.append(str(arg))
        
        for k, v in sorted(kwargs.items()):
            if isinstance(v, (dict, list)):
                key_parts.append(f"{k}={json.dumps(v, sort_keys=True)}")
            else:
                key_parts.append(f"{k}={v}")
        
        # 生成 MD5 哈希
        key_str = ":".join(key_parts)
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        
        return f"{prefix}:{key_hash}"
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在返回 None
        """
        # 仅从内存缓存获取（Redis已禁用）
        if key in self.memory_cache:
            entry = self.memory_cache[key]
            # 检查是否过期
            if entry["expire_at"] is None or entry["expire_at"] > time.time():
                self.cache_stats["hits"] += 1
                logger.debug(f"内存缓存命中: {key}")
                return entry["value"]
            else:
                # 过期，删除
                del self.memory_cache[key]
        
        self.cache_stats["misses"] += 1
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 表示永不过期
        """
        ttl = ttl if ttl is not None else self.default_ttl
        expire_at = time.time() + ttl if ttl > 0 else None
        
        # 仅设置内存缓存（Redis已禁用）
        self.memory_cache[key] = {
            "value": value,
            "expire_at": expire_at
        }
        
        self.cache_stats["sets"] += 1
    
    def delete(self, key: str):
        """
        删除缓存（仅内存缓存，不操作Redis）
        
        Args:
            key: 缓存键
        """
        # 删除内存缓存
        if key in self.memory_cache:
            del self.memory_cache[key]
        
        self.cache_stats["deletes"] += 1
    
    def clear(self, pattern: Optional[str] = None):
        """
        清空缓存（仅内存缓存，不操作Redis）
        
        Args:
            pattern: 键模式（可选），如 "llm:*"
        """
        if pattern:
            # 清空匹配的键
            keys_to_delete = [k for k in self.memory_cache.keys() if k.startswith(pattern.replace("*", ""))]
            for key in keys_to_delete:
                del self.memory_cache[key]
        else:
            # 清空所有缓存
            self.memory_cache.clear()
    
    def get_stats(self) -> dict:
        """
        获取缓存统计
        
        Returns:
            缓存统计信息
        """
        total_requests = self.cache_stats["hits"] + self.cache_stats["misses"]
        hit_rate = self.cache_stats["hits"] / total_requests if total_requests > 0 else 0
        
        return {
            **self.cache_stats,
            "total_requests": total_requests,
            "hit_rate": hit_rate,
            "memory_cache_size": len(self.memory_cache)
        }
    
    def cached(self, prefix: str, ttl: Optional[int] = None):
        """
        缓存装饰器
        
        Args:
            prefix: 缓存键前缀
            ttl: 过期时间（秒）
            
        Returns:
            装饰器函数
        """
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # 生成缓存键
                cache_key = self._generate_key(prefix, *args, **kwargs)
                
                # 尝试从缓存获取
                cached_value = self.get(cache_key)
                if cached_value is not None:
                    return cached_value
                
                # 执行函数
                result = func(*args, **kwargs)
                
                # 设置缓存
                self.set(cache_key, result, ttl)
                
                return result
            
            return wrapper
        return decorator


# 全局缓存管理器实例
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """
    获取全局缓存管理器实例（仅使用内存缓存，不使用Redis）
    
    Returns:
        缓存管理器实例
    """
    global _cache_manager
    if _cache_manager is None:
        # 强制禁用Redis，仅使用内存缓存
        logger.info("✓ 初始化缓存管理器（仅使用内存缓存，Redis已禁用）")
        _cache_manager = CacheManager(redis_client=None, default_ttl=3600)
    
    return _cache_manager


def cached(prefix: str, ttl: Optional[int] = None):
    """
    缓存装饰器（便捷方法）
    
    Args:
        prefix: 缓存键前缀
        ttl: 过期时间（秒）
        
    Returns:
        装饰器函数
    """
    cache_manager = get_cache_manager()
    return cache_manager.cached(prefix, ttl)


# LRU 缓存装饰器（用于简单场景）
def lru_cached(maxsize: int = 128):
    """
    LRU 缓存装饰器
    
    Args:
        maxsize: 最大缓存数量
        
    Returns:
        装饰器函数
    """
    return lru_cache(maxsize=maxsize)
