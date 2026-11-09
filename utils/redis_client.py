"""
Redis 客户端工具

提供 Redis 连接管理和便捷操作

⚠️ 安全限制：
- 禁止所有删除操作（delete、flushdb、flushall）
- Redis仅用于查询验证码，不用于缓存
- 缓存功能已改为仅使用内存缓存
"""
import logging
from typing import Optional
import os

logger = logging.getLogger(__name__)

# 全局 Redis 客户端实例
_redis_client: Optional[object] = None

# ⚠️ 安全警告：禁止Redis删除操作
# Redis仅用于查询验证码，不允许任何删除操作
REDIS_DELETE_FORBIDDEN = True
FORBIDDEN_REDIS_METHODS = {"delete", "unlink", "flushdb", "flushall"}
FORBIDDEN_REDIS_COMMANDS = {"DEL", "UNLINK", "FLUSHDB", "FLUSHALL"}


class SafeRedisClient:
    """Redis 安全代理：禁止所有清除/删除类操作。"""

    def __init__(self, client: object):
        self._client = client

    def _forbid(self, operation_name: str):
        _forbidden_operation(operation_name)

    def execute_command(self, *args, **kwargs):
        if args:
            command = str(args[0]).strip().upper()
            if command in FORBIDDEN_REDIS_COMMANDS:
                self._forbid(f"redis_execute_command:{command}")
        return self._client.execute_command(*args, **kwargs)

    def __getattr__(self, name: str):
        if name.lower() in FORBIDDEN_REDIS_METHODS:
            def _blocked(*args, **kwargs):
                self._forbid(f"redis_client.{name}")
            return _blocked
        return getattr(self._client, name)


def wrap_safe_redis_client(client: object) -> object:
    """将原生 Redis 客户端包装为安全客户端。"""
    if client is None or isinstance(client, SafeRedisClient):
        return client
    return SafeRedisClient(client)


def create_redis_client(
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    password: Optional[str] = None,
    socket_timeout: int = 5,
    socket_connect_timeout: int = 5,
    decode_responses: bool = True,
    max_connections: int = 50,
    **kwargs
) -> Optional[object]:
    """
    创建 Redis 客户端
    
    Args:
        host: Redis 主机地址
        port: Redis 端口
        db: Redis 数据库编号
        password: Redis 密码
        socket_timeout: Socket 超时时间（秒）
        socket_connect_timeout: Socket 连接超时时间（秒）
        decode_responses: 是否自动解码响应
        max_connections: 最大连接数
        **kwargs: 其他参数
        
    Returns:
        Redis 客户端实例，如果 redis 模块未安装则返回 None
    """
    try:
        import redis
        
        # 创建连接池
        pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            decode_responses=decode_responses,
            max_connections=max_connections,
            **kwargs
        )
        
        # 创建 Redis 客户端
        client = redis.Redis(connection_pool=pool)
        
        # 测试连接
        client.ping()
        
        logger.info(
            f"✓ Redis 客户端已创建 "
            f"(host={host}, port={port}, db={db})"
        )
        
        return wrap_safe_redis_client(client)
        
    except ImportError:
        logger.warning(
            "Redis 模块未安装，无法使用 Redis 缓存。"
            "安装方法: pip install redis"
        )
        return None
    except Exception as e:
        logger.error(f"Redis 连接失败: {e}")
        return None


def get_redis_client() -> Optional[object]:
    """
    获取全局 Redis 客户端实例
    
    Returns:
        Redis 客户端实例，如果未初始化或连接失败则返回 None
    """
    global _redis_client
    
    if _redis_client is None:
        # 尝试从环境变量或配置文件加载
        try:
            # 优先从环境变量读取
            host = os.getenv("REDIS_HOST")
            port = int(os.getenv("REDIS_PORT", "6379"))
            db = int(os.getenv("REDIS_DB", "0"))
            password = os.getenv("REDIS_PASSWORD")
            
            # 如果环境变量未设置，尝试从配置文件读取
            if not host:
                from utils.config_loader import ConfigLoader
                config = ConfigLoader.load_framework_config("redis_config.json")
                
                redis_config = config.get("redis", {})
                
                # 检查是否启用 Redis
                if not redis_config.get("enabled", False):
                    logger.info("Redis 未启用（配置文件中 enabled=false）")
                    return None
                
                host = redis_config.get("host", "localhost")
                port = redis_config.get("port", 6379)
                db = redis_config.get("db", 0)
                password = redis_config.get("password")
            
            # 如果 host 仍然是占位符或默认值，跳过连接
            if not host or host == "localhost" or host == "your_redis_host":
                logger.info("Redis 未配置（使用默认值或占位符）")
                return None
            
            # 创建 Redis 客户端
            _redis_client = create_redis_client(
                host=host,
                port=port,
                db=db,
                password=password,
                socket_timeout=5,
                socket_connect_timeout=5,
                decode_responses=True,
                max_connections=50
            )
            
        except Exception as e:
            logger.warning(f"Redis 客户端初始化失败: {e}")
            _redis_client = None
    
    return _redis_client


def close_redis_client():
    """关闭 Redis 客户端连接"""
    global _redis_client
    
    if _redis_client is not None:
        try:
            _redis_client.close()
            logger.info("✓ Redis 客户端已关闭")
        except Exception as e:
            logger.warning(f"Redis 客户端关闭失败: {e}")
        finally:
            _redis_client = None


def test_redis_connection() -> bool:
    """
    测试 Redis 连接
    
    Returns:
        连接是否成功
    """
    client = get_redis_client()
    
    if client is None:
        return False
    
    try:
        client.ping()
        logger.info("✓ Redis 连接测试成功")
        return True
    except Exception as e:
        logger.error(f"Redis 连接测试失败: {e}")
        return False


# 便捷函数
def redis_get(key: str) -> Optional[str]:
    """
    获取 Redis 值
    
    Args:
        key: 键
        
    Returns:
        值，如果不存在或连接失败则返回 None
    """
    client = get_redis_client()
    if client is None:
        return None
    
    try:
        return client.get(key)
    except Exception as e:
        logger.warning(f"Redis GET 失败: {e}")
        return None


def redis_set(key: str, value: str, ttl: Optional[int] = None) -> bool:
    """
    设置 Redis 值
    
    Args:
        key: 键
        value: 值
        ttl: 过期时间（秒），None 表示永不过期
        
    Returns:
        是否成功
    """
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        if ttl is not None:
            client.setex(key, ttl, value)
        else:
            client.set(key, value)
        return True
    except Exception as e:
        logger.warning(f"Redis SET 失败: {e}")
        return False


def redis_exists(key: str) -> bool:
    """
    检查 Redis 键是否存在
    
    Args:
        key: 键
        
    Returns:
        是否存在
    """
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        return client.exists(key) > 0
    except Exception as e:
        logger.warning(f"Redis EXISTS 失败: {e}")
        return False


# ============================================================================
# ⚠️ 安全保护：禁止Redis删除操作
# ============================================================================

def _forbidden_operation(operation_name: str):
    """
    禁止的Redis操作
    
    Args:
        operation_name: 操作名称
        
    Raises:
        RuntimeError: 始终抛出异常，禁止操作
    """
    error_msg = (
        f"❌ 禁止的操作: {operation_name}\n"
        f"Redis仅用于查询验证码，不允许任何删除操作。\n"
        f"如需清除缓存，请重启服务。"
    )
    logger.error(error_msg)
    raise RuntimeError(error_msg)


def redis_delete(key: str) -> bool:
    """
    ❌ 已禁用：删除Redis键
    
    此函数已被禁用以防止误操作。
    Redis仅用于查询验证码，不允许删除操作。
    
    Args:
        key: 键
        
    Raises:
        RuntimeError: 始终抛出异常
    """
    _forbidden_operation("redis_delete")


def redis_flushdb() -> bool:
    """
    ❌ 已禁用：清空当前数据库
    
    此函数已被禁用以防止误操作。
    Redis仅用于查询验证码，不允许删除操作。
    
    Raises:
        RuntimeError: 始终抛出异常
    """
    _forbidden_operation("redis_flushdb")


def redis_flushall() -> bool:
    """
    ❌ 已禁用：清空所有数据库
    
    此函数已被禁用以防止误操作。
    Redis仅用于查询验证码，不允许删除操作。
    
    Raises:
        RuntimeError: 始终抛出异常
    """
    _forbidden_operation("redis_flushall")


# ============================================================================
# 使用说明
# ============================================================================
"""
Redis使用限制：

1. ✅ 允许的操作：
   - redis_get(key)          # 读取数据
   - redis_set(key, value)   # 写入数据
   - redis_exists(key)       # 检查键是否存在
   - test_redis_connection() # 测试连接

2. ❌ 禁止的操作：
   - redis_delete(key)       # 删除键 - 已禁用
   - redis_flushdb()         # 清空数据库 - 已禁用
   - redis_flushall()        # 清空所有数据库 - 已禁用
   - 任何直接调用 client.delete() 的操作

3. 📋 使用场景：
   - Redis仅用于查询验证码（business_logic/user/verify_code_service.py）
   - 缓存功能已改为仅使用内存缓存（utils/cache_manager.py）
   - 幂等性缓存已改为仅使用内存缓存（utils/idempotent.py）

4. 🔄 如需清除缓存：
   - 重启服务即可清除内存缓存
   - 不要尝试清除Redis数据
"""
