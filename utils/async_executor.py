"""
异步执行器

支持多种异步执行模式：
1. 线程池执行（I/O 密集型任务）
2. 进程池执行（CPU 密集型任务）
3. 异步任务队列（后台任务）

使用场景：
- 并发 LLM 调用
- 批量数据库操作
- 后台任务处理
"""
from typing import Any, Callable, List, Optional
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, Future
import asyncio
import logging
from functools import wraps
import time

logger = logging.getLogger(__name__)


class AsyncExecutor:
    """异步执行器"""
    
    def __init__(
        self, 
        max_workers: int = 10,
        executor_type: str = "thread"
    ):
        """
        初始化异步执行器
        
        Args:
            max_workers: 最大工作线程/进程数
            executor_type: 执行器类型（"thread" 或 "process"）
        """
        self.max_workers = max_workers
        self.executor_type = executor_type
        
        if executor_type == "thread":
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
        elif executor_type == "process":
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
        else:
            raise ValueError(f"不支持的执行器类型: {executor_type}")
        
        self.tasks = []
        logger.info(f"✓ 异步执行器初始化完成: {executor_type}, max_workers={max_workers}")
    
    def submit(self, func: Callable, *args, **kwargs) -> Future:
        """
        提交任务
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Future 对象
        """
        future = self.executor.submit(func, *args, **kwargs)
        self.tasks.append(future)
        return future
    
    def map(self, func: Callable, *iterables, timeout: Optional[float] = None) -> List[Any]:
        """
        并发执行多个任务
        
        Args:
            func: 要执行的函数
            *iterables: 可迭代对象
            timeout: 超时时间（秒）
            
        Returns:
            结果列表
        """
        return list(self.executor.map(func, *iterables, timeout=timeout))
    
    def wait_all(self, timeout: Optional[float] = None) -> List[Any]:
        """
        等待所有任务完成
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            结果列表
        """
        results = []
        for future in self.tasks:
            try:
                result = future.result(timeout=timeout)
                results.append(result)
            except Exception as e:
                logger.error(f"任务执行失败: {e}")
                results.append(None)
        
        self.tasks.clear()
        return results
    
    def shutdown(self, wait: bool = True):
        """
        关闭执行器
        
        Args:
            wait: 是否等待任务完成
        """
        self.executor.shutdown(wait=wait)
        logger.info("✓ 异步执行器已关闭")
    
    def async_run(self, timeout: Optional[float] = None):
        """
        异步执行装饰器
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            装饰器函数
        """
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                future = self.submit(func, *args, **kwargs)
                return future.result(timeout=timeout)
            
            return wrapper
        return decorator


class AsyncTaskQueue:
    """异步任务队列"""
    
    def __init__(self, max_workers: int = 5):
        """
        初始化异步任务队列
        
        Args:
            max_workers: 最大工作线程数
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.queue = []
        self.results = {}
        logger.info(f"✓ 异步任务队列初始化完成: max_workers={max_workers}")
    
    def add_task(self, task_id: str, func: Callable, *args, **kwargs):
        """
        添加任务到队列
        
        Args:
            task_id: 任务 ID
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
        """
        future = self.executor.submit(func, *args, **kwargs)
        self.queue.append({
            "task_id": task_id,
            "future": future,
            "start_time": time.time()
        })
        logger.info(f"任务已添加到队列: {task_id}")
    
    def get_task_status(self, task_id: str) -> dict:
        """
        获取任务状态
        
        Args:
            task_id: 任务 ID
            
        Returns:
            任务状态
        """
        # 检查队列中的任务
        for task in self.queue:
            if task["task_id"] == task_id:
                future = task["future"]
                if future.done():
                    try:
                        result = future.result()
                        self.results[task_id] = result
                        self.queue.remove(task)
                        return {
                            "status": "completed",
                            "result": result,
                            "duration": time.time() - task["start_time"]
                        }
                    except Exception as e:
                        self.queue.remove(task)
                        return {
                            "status": "failed",
                            "error": str(e),
                            "duration": time.time() - task["start_time"]
                        }
                else:
                    return {
                        "status": "running",
                        "duration": time.time() - task["start_time"]
                    }
        
        # 检查已完成的任务
        if task_id in self.results:
            return {
                "status": "completed",
                "result": self.results[task_id]
            }
        
        return {
            "status": "not_found"
        }
    
    def get_all_tasks(self) -> List[dict]:
        """
        获取所有任务状态
        
        Returns:
            任务状态列表
        """
        tasks = []
        for task in self.queue:
            tasks.append({
                "task_id": task["task_id"],
                "status": "completed" if task["future"].done() else "running",
                "duration": time.time() - task["start_time"]
            })
        return tasks
    
    def shutdown(self, wait: bool = True):
        """
        关闭任务队列
        
        Args:
            wait: 是否等待任务完成
        """
        self.executor.shutdown(wait=wait)
        logger.info("✓ 异步任务队列已关闭")


# 全局异步执行器实例
_async_executor: Optional[AsyncExecutor] = None
_async_task_queue: Optional[AsyncTaskQueue] = None


def get_async_executor() -> AsyncExecutor:
    """
    获取全局异步执行器实例
    
    Returns:
        异步执行器实例
    """
    global _async_executor
    if _async_executor is None:
        _async_executor = AsyncExecutor(max_workers=10, executor_type="thread")
    return _async_executor


def get_async_task_queue() -> AsyncTaskQueue:
    """
    获取全局异步任务队列实例
    
    Returns:
        异步任务队列实例
    """
    global _async_task_queue
    if _async_task_queue is None:
        _async_task_queue = AsyncTaskQueue(max_workers=5)
    return _async_task_queue


def async_run(timeout: Optional[float] = None):
    """
    异步执行装饰器（便捷方法）
    
    Args:
        timeout: 超时时间（秒）
        
    Returns:
        装饰器函数
    """
    executor = get_async_executor()
    return executor.async_run(timeout)


# 批量并发执行
def batch_execute(func: Callable, items: List[Any], max_workers: int = 10) -> List[Any]:
    """
    批量并发执行
    
    Args:
        func: 要执行的函数
        items: 要处理的项目列表
        max_workers: 最大工作线程数
        
    Returns:
        结果列表
    """
    executor = AsyncExecutor(max_workers=max_workers, executor_type="thread")
    results = executor.map(func, items)
    executor.shutdown()
    return results


# 异步上下文管理器
class AsyncContext:
    """异步上下文管理器"""
    
    def __init__(self, max_workers: int = 10):
        self.executor = AsyncExecutor(max_workers=max_workers, executor_type="thread")
    
    def __enter__(self):
        return self.executor
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.executor.shutdown(wait=True)
        return False
