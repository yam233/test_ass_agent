"""
全链路追踪工具

提供轻量级的链路追踪功能，无需外部依赖
支持异步和同步函数
"""
import time
import uuid
import asyncio
import functools
import logging
from typing import Dict, Any, Optional, Callable
from contextvars import ContextVar
from datetime import datetime

logger = logging.getLogger(__name__)

# 当前追踪上下文
_current_trace_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    'trace_context', 
    default=None
)


class Span:
    """追踪 Span"""
    
    def __init__(
        self, 
        name: str, 
        trace_id: str,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None
    ):
        """
        初始化 Span
        
        Args:
            name: Span 名称
            trace_id: 追踪 ID
            parent_span_id: 父 Span ID
            attributes: 属性
        """
        self.span_id = str(uuid.uuid4())[:8]
        self.name = name
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.attributes = attributes or {}
        self.start_time = None
        self.end_time = None
        self.duration_ms = None
        self.success = True
        self.error = None
    
    def start(self):
        """开始 Span"""
        self.start_time = time.time()
        logger.debug(
            f"[Trace] Span started: {self.name} "
            f"(trace_id={self.trace_id}, span_id={self.span_id})"
        )
    
    def end(self, success: bool = True, error: Optional[str] = None):
        """
        结束 Span
        
        Args:
            success: 是否成功
            error: 错误信息
        """
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        self.error = error
        
        logger.info(
            f"[Trace] Span ended: {self.name} "
            f"(trace_id={self.trace_id}, span_id={self.span_id}, "
            f"duration={self.duration_ms:.2f}ms, success={success})"
        )
    
    def set_attribute(self, key: str, value: Any):
        """
        设置属性
        
        Args:
            key: 属性键
            value: 属性值
        """
        self.attributes[key] = value
    
    def record_exception(self, exception: Exception):
        """
        记录异常
        
        Args:
            exception: 异常对象
        """
        self.error = f"{type(exception).__name__}: {str(exception)}"
        self.success = False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            Span 字典
        """
        return {
            "span_id": self.span_id,
            "name": self.name,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else None,
            "end_time": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "attributes": self.attributes
        }


class TraceContext:
    """追踪上下文"""
    
    def __init__(self, trace_id: Optional[str] = None):
        """
        初始化追踪上下文
        
        Args:
            trace_id: 追踪 ID（如果为 None 则自动生成）
        """
        self.trace_id = trace_id or str(uuid.uuid4())[:16]
        self.spans = []
        self.current_span = None
    
    def start_span(
        self, 
        name: str, 
        attributes: Optional[Dict[str, Any]] = None
    ) -> Span:
        """
        开始一个新的 Span
        
        Args:
            name: Span 名称
            attributes: 属性
            
        Returns:
            Span 对象
        """
        parent_span_id = self.current_span.span_id if self.current_span else None
        span = Span(name, self.trace_id, parent_span_id, attributes)
        span.start()
        self.spans.append(span)
        self.current_span = span
        return span
    
    def end_span(self, success: bool = True, error: Optional[str] = None):
        """
        结束当前 Span
        
        Args:
            success: 是否成功
            error: 错误信息
        """
        if self.current_span:
            self.current_span.end(success, error)
            
            # 恢复父 Span
            if self.current_span.parent_span_id:
                for span in reversed(self.spans):
                    if span.span_id == self.current_span.parent_span_id:
                        self.current_span = span
                        break
            else:
                self.current_span = None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            追踪上下文字典
        """
        return {
            "trace_id": self.trace_id,
            "spans": [span.to_dict() for span in self.spans]
        }


def get_current_trace_context() -> Optional[TraceContext]:
    """
    获取当前追踪上下文
    
    Returns:
        追踪上下文
    """
    return _current_trace_context.get()


def set_current_trace_context(context: Optional[TraceContext]):
    """
    设置当前追踪上下文
    
    Args:
        context: 追踪上下文
    """
    _current_trace_context.set(context)


def trace_span(
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None
):
    """
    追踪 Span 装饰器（支持异步和同步函数）
    
    Args:
        name: Span 名称（如果为 None 则使用函数名）
        attributes: 属性
        
    Returns:
        装饰器函数
    
    Example:
        @trace_span("intent_recognition")
        async def recognize_intent(user_input: str):
            # 意图识别逻辑
            pass
    """
    def decorator(func: Callable):
        span_name = name or func.__name__
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 获取或创建追踪上下文
            context = get_current_trace_context()
            if context is None:
                context = TraceContext()
                set_current_trace_context(context)
            
            # 开始 Span
            span = context.start_span(span_name, attributes)
            
            try:
                # 执行函数
                result = await func(*args, **kwargs)
                
                # 结束 Span（成功）
                context.end_span(success=True)
                
                return result
            except Exception as e:
                # 记录异常
                span.record_exception(e)
                
                # 结束 Span（失败）
                context.end_span(success=False, error=str(e))
                
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 获取或创建追踪上下文
            context = get_current_trace_context()
            if context is None:
                context = TraceContext()
                set_current_trace_context(context)
            
            # 开始 Span
            span = context.start_span(span_name, attributes)
            
            try:
                # 执行函数
                result = func(*args, **kwargs)
                
                # 结束 Span（成功）
                context.end_span(success=True)
                
                return result
            except Exception as e:
                # 记录异常
                span.record_exception(e)
                
                # 结束 Span（失败）
                context.end_span(success=False, error=str(e))
                
                raise
        
        # 根据函数类型返回对应的包装器
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def get_trace_summary() -> Optional[Dict[str, Any]]:
    """
    获取当前追踪摘要
    
    Returns:
        追踪摘要
    """
    context = get_current_trace_context()
    if context is None:
        return None
    
    return context.to_dict()


def clear_trace_context():
    """清空追踪上下文"""
    set_current_trace_context(None)
