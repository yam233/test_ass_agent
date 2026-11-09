"""
超时保护工具

提供超时装饰器，防止函数执行时间过长
"""
import asyncio
import time
from functools import wraps
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)


def async_timeout(seconds: float, error_message: Optional[str] = None):
    """
    异步超时装饰器
    
    Args:
        seconds: 超时时间（秒）
        error_message: 自定义错误消息
        
    Returns:
        装饰器函数
        
    Example:
        @async_timeout(5.0)
        async def my_function():
            await asyncio.sleep(10)  # 会在 5 秒后超时
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs), 
                    timeout=seconds
                )
            except asyncio.TimeoutError:
                func_name = func.__name__
                msg = error_message or f"{func_name} 执行超时（{seconds}秒）"
                logger.error(msg)
                raise TimeoutError(msg)
        return wrapper
    return decorator


def sync_timeout(seconds: float, error_message: Optional[str] = None):
    """
    同步超时装饰器（使用 signal，仅支持 Unix 系统）
    
    注意：此装饰器仅在 Unix 系统上有效，Windows 不支持
    
    Args:
        seconds: 超时时间（秒）
        error_message: 自定义错误消息
        
    Returns:
        装饰器函数
        
    Example:
        @sync_timeout(5.0)
        def my_function():
            time.sleep(10)  # 会在 5 秒后超时
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import signal
            
            def timeout_handler(signum, frame):
                func_name = func.__name__
                msg = error_message or f"{func_name} 执行超时（{seconds}秒）"
                raise TimeoutError(msg)
            
            # 设置超时信号
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(seconds))
            
            try:
                result = func(*args, **kwargs)
            finally:
                # 取消超时信号
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            
            return result
        return wrapper
    return decorator


class TimeoutContext:
    """
    超时上下文管理器（用于代码块）
    
    Example:
        async with TimeoutContext(5.0):
            await some_long_operation()
    """
    
    def __init__(self, seconds: float, error_message: Optional[str] = None):
        """
        初始化超时上下文
        
        Args:
            seconds: 超时时间（秒）
            error_message: 自定义错误消息
        """
        self.seconds = seconds
        self.error_message = error_message
    
    async def __aenter__(self):
        """进入上下文"""
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        elapsed = time.time() - self.start_time
        if elapsed > self.seconds:
            msg = self.error_message or f"操作超时（{self.seconds}秒）"
            logger.warning(f"{msg}，实际耗时 {elapsed:.2f}秒")
        return False


# 便捷函数
async def run_with_timeout(coro, seconds: float, error_message: Optional[str] = None):
    """
    运行协程并设置超时
    
    Args:
        coro: 协程对象
        seconds: 超时时间（秒）
        error_message: 自定义错误消息
        
    Returns:
        协程执行结果
        
    Raises:
        TimeoutError: 超时异常
        
    Example:
        result = await run_with_timeout(
            some_async_function(),
            timeout=5.0
        )
    """
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        msg = error_message or f"操作超时（{seconds}秒）"
        logger.error(msg)
        raise TimeoutError(msg)
