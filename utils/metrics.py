"""
性能监控和指标收集

收集系统运行指标，支持导出 Prometheus 格式
"""
import time
import logging
from typing import Dict, Any, Optional
from collections import defaultdict
from datetime import datetime
import threading


logger = logging.getLogger(__name__)


class MetricsCollector:
    """指标收集器"""
    
    def __init__(self):
        """初始化指标收集器"""
        self.lock = threading.Lock()
        
        # 计数器
        self.counters = defaultdict(int)
        
        # 直方图（用于记录耗时）
        self.histograms = defaultdict(list)
        
        # 仪表盘（用于记录当前值）
        self.gauges = {}
        
        # 最近的错误
        self.recent_errors = []
        self.max_errors = 100
    
    def increment(self, name: str, value: int = 1, labels: Optional[Dict[str, str]] = None):
        """
        增加计数器
        
        Args:
            name: 指标名称
            value: 增加值
            labels: 标签
        """
        with self.lock:
            key = self._make_key(name, labels)
            self.counters[key] += value
    
    def record_duration(self, name: str, duration_ms: float, labels: Optional[Dict[str, str]] = None):
        """
        记录耗时
        
        Args:
            name: 指标名称
            duration_ms: 耗时（毫秒）
            labels: 标签
        """
        with self.lock:
            key = self._make_key(name, labels)
            self.histograms[key].append(duration_ms)
            
            # 只保留最近1000条记录
            if len(self.histograms[key]) > 1000:
                self.histograms[key] = self.histograms[key][-1000:]
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """
        设置仪表盘值
        
        Args:
            name: 指标名称
            value: 值
            labels: 标签
        """
        with self.lock:
            key = self._make_key(name, labels)
            self.gauges[key] = value
    
    def record_error(self, error: str, context: Optional[Dict[str, Any]] = None):
        """
        记录错误
        
        Args:
            error: 错误信息
            context: 上下文信息
        """
        with self.lock:
            error_record = {
                "timestamp": datetime.now().isoformat(),
                "error": error,
                "context": context or {}
            }
            self.recent_errors.append(error_record)
            
            # 只保留最近的错误
            if len(self.recent_errors) > self.max_errors:
                self.recent_errors = self.recent_errors[-self.max_errors:]
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        获取所有指标
        
        Returns:
            指标字典
        """
        with self.lock:
            metrics = {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "histograms": {},
                "recent_errors": list(self.recent_errors)
            }
            
            # 计算直方图统计信息
            for key, values in self.histograms.items():
                if values:
                    metrics["histograms"][key] = {
                        "count": len(values),
                        "sum": sum(values),
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values),
                        "p50": self._percentile(values, 50),
                        "p95": self._percentile(values, 95),
                        "p99": self._percentile(values, 99)
                    }
            
            return metrics
    
    def reset(self):
        """重置所有指标"""
        with self.lock:
            self.counters.clear()
            self.histograms.clear()
            self.gauges.clear()
            self.recent_errors.clear()
    
    def _make_key(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        """
        生成指标键
        
        Args:
            name: 指标名称
            labels: 标签
            
        Returns:
            指标键
        """
        if not labels:
            return name
        
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def _percentile(self, values: list, percentile: int) -> float:
        """
        计算百分位数
        
        Args:
            values: 值列表
            percentile: 百分位（0-100）
            
        Returns:
            百分位值
        """
        if not values:
            return 0.0
        
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile / 100)
        return sorted_values[min(index, len(sorted_values) - 1)]


class Timer:
    """计时器上下文管理器"""
    
    def __init__(self, collector: MetricsCollector, name: str, labels: Optional[Dict[str, str]] = None):
        """
        初始化计时器
        
        Args:
            collector: 指标收集器
            name: 指标名称
            labels: 标签
        """
        self.collector = collector
        self.name = name
        self.labels = labels
        self.start_time = None
    
    def __enter__(self):
        """进入上下文"""
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        if self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            self.collector.record_duration(self.name, duration_ms, self.labels)


# 全局指标收集器
_metrics_collector = None


def get_metrics_collector() -> MetricsCollector:
    """
    获取全局指标收集器
    
    Returns:
        MetricsCollector 实例
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def increment_counter(name: str, value: int = 1, labels: Optional[Dict[str, str]] = None):
    """增加计数器"""
    collector = get_metrics_collector()
    collector.increment(name, value, labels)


def record_duration(name: str, duration_ms: float, labels: Optional[Dict[str, str]] = None):
    """记录耗时"""
    collector = get_metrics_collector()
    collector.record_duration(name, duration_ms, labels)


def set_gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None):
    """设置仪表盘值"""
    collector = get_metrics_collector()
    collector.set_gauge(name, value, labels)


def record_error(error: str, context: Optional[Dict[str, Any]] = None):
    """记录错误"""
    collector = get_metrics_collector()
    collector.record_error(error, context)


def timer(name: str, labels: Optional[Dict[str, str]] = None) -> Timer:
    """
    创建计时器
    
    Args:
        name: 指标名称
        labels: 标签
        
    Returns:
        Timer 实例
    
    Example:
        with timer("skill_execution", {"skill": "execute_gift_issue"}):
            # 执行代码
            pass
    """
    collector = get_metrics_collector()
    return Timer(collector, name, labels)


def get_metrics() -> Dict[str, Any]:
    """获取所有指标"""
    collector = get_metrics_collector()
    return collector.get_metrics()


def reset_metrics():
    """重置所有指标"""
    collector = get_metrics_collector()
    collector.reset()
