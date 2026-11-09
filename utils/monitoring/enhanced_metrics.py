"""
增强的指标监控系统

扩展现有 metrics.py，添加更详细的业务指标
"""
import logging
from typing import Dict, Any, Optional
from utils.metrics import get_metrics_collector, timer

logger = logging.getLogger(__name__)


class BusinessMetrics:
    """业务指标收集器"""
    
    def __init__(self):
        """初始化业务指标收集器"""
        self.collector = get_metrics_collector()
    
    # ============ HTTP 请求指标 ============
    
    def record_http_request(
        self,
        endpoint: str,
        method: str = "POST",
        status_code: int = 200,
        duration_ms: float = 0
    ):
        """
        记录 HTTP 请求
        
        Args:
            endpoint: 端点
            method: HTTP 方法
            status_code: 状态码
            duration_ms: 耗时（毫秒）
        """
        # 请求总数
        self.collector.increment(
            "http_requests_total",
            labels={
                "endpoint": endpoint,
                "method": method,
                "status": str(status_code)
            }
        )
        
        # 请求耗时
        self.collector.record_duration(
            "http_request_duration_ms",
            duration_ms,
            labels={"endpoint": endpoint}
        )
        
        # 错误请求
        if status_code >= 400:
            self.collector.increment(
                "http_requests_errors_total",
                labels={
                    "endpoint": endpoint,
                    "status": str(status_code)
                }
            )
    
    # ============ LLM 调用指标 ============
    
    def record_llm_call(
        self,
        model: str,
        call_type: str,  # intent/params
        success: bool,
        duration_ms: float,
        token_usage: Optional[Dict[str, int]] = None,
        cache_hit: bool = False
    ):
        """
        记录 LLM 调用
        
        Args:
            model: 模型名称
            call_type: 调用类型（intent/params）
            success: 是否成功
            duration_ms: 耗时（毫秒）
            token_usage: Token 使用量 {prompt: int, completion: int}
            cache_hit: 是否缓存命中
        """
        # LLM 调用总数
        self.collector.increment(
            "llm_calls_total",
            labels={
                "model": model,
                "type": call_type,
                "success": str(success),
                "cache_hit": str(cache_hit)
            }
        )
        
        # LLM 调用耗时
        self.collector.record_duration(
            "llm_call_duration_ms",
            duration_ms,
            labels={
                "model": model,
                "type": call_type
            }
        )
        
        # Token 使用量
        if token_usage:
            self.collector.increment(
                "llm_token_usage_total",
                value=token_usage.get("prompt", 0),
                labels={
                    "model": model,
                    "type": "prompt"
                }
            )
            self.collector.increment(
                "llm_token_usage_total",
                value=token_usage.get("completion", 0),
                labels={
                    "model": model,
                    "type": "completion"
                }
            )
        
        # 缓存命中率
        if cache_hit:
            self.collector.increment(
                "llm_cache_hits_total",
                labels={"model": model, "type": call_type}
            )
        else:
            self.collector.increment(
                "llm_cache_misses_total",
                labels={"model": model, "type": call_type}
            )
    
    # ============ Skill 执行指标 ============
    
    def record_skill_execution(
        self,
        business_code: str,
        skill_name: str,
        skill_type: str,  # query/execute
        success: bool,
        duration_ms: float,
        error_type: Optional[str] = None
    ):
        """
        记录 Skill 执行
        
        Args:
            business_code: 业务代码
            skill_name: Skill 名称
            skill_type: Skill 类型
            success: 是否成功
            duration_ms: 耗时（毫秒）
            error_type: 错误类型
        """
        # Skill 执行总数
        self.collector.increment(
            "skill_executions_total",
            labels={
                "business_code": business_code,
                "skill_name": skill_name,
                "skill_type": skill_type,
                "success": str(success)
            }
        )
        
        # Skill 执行耗时
        self.collector.record_duration(
            "skill_execution_duration_ms",
            duration_ms,
            labels={
                "business_code": business_code,
                "skill_name": skill_name
            }
        )
        
        # Skill 错误
        if not success and error_type:
            self.collector.increment(
                "skill_errors_total",
                labels={
                    "business_code": business_code,
                    "skill_name": skill_name,
                    "error_type": error_type
                }
            )
    
    # ============ 意图识别指标 ============
    
    def record_intent_recognition(
        self,
        business_code: str,
        skill_name: str,
        confidence: float,
        duration_ms: float,
        cache_hit: bool = False
    ):
        """
        记录意图识别
        
        Args:
            business_code: 业务代码
            skill_name: 识别的 Skill 名称
            confidence: 置信度
            duration_ms: 耗时（毫秒）
            cache_hit: 是否缓存命中
        """
        # 意图识别总数
        self.collector.increment(
            "intent_recognitions_total",
            labels={
                "business_code": business_code,
                "skill_name": skill_name,
                "cache_hit": str(cache_hit)
            }
        )
        
        # 意图识别耗时
        self.collector.record_duration(
            "intent_recognition_duration_ms",
            duration_ms,
            labels={"business_code": business_code}
        )
        
        # 置信度分布
        confidence_bucket = self._get_confidence_bucket(confidence)
        self.collector.increment(
            "intent_confidence_distribution",
            labels={
                "business_code": business_code,
                "bucket": confidence_bucket
            }
        )
    
    # ============ 参数提取指标 ============
    
    def record_param_extraction(
        self,
        business_code: str,
        skill_name: str,
        param_count: int,
        duration_ms: float,
        validation_success: bool
    ):
        """
        记录参数提取
        
        Args:
            business_code: 业务代码
            skill_name: Skill 名称
            param_count: 提取的参数数量
            duration_ms: 耗时（毫秒）
            validation_success: 验证是否成功
        """
        # 参数提取总数
        self.collector.increment(
            "param_extractions_total",
            labels={
                "business_code": business_code,
                "skill_name": skill_name,
                "validation_success": str(validation_success)
            }
        )
        
        # 参数提取耗时
        self.collector.record_duration(
            "param_extraction_duration_ms",
            duration_ms,
            labels={"business_code": business_code}
        )
        
        # 参数数量
        self.collector.set_gauge(
            "param_count",
            param_count,
            labels={
                "business_code": business_code,
                "skill_name": skill_name
            }
        )
    
    # ============ 缓存指标 ============
    
    def record_cache_operation(
        self,
        cache_type: str,  # intent/llm/config
        operation: str,   # hit/miss/set/clear
        key: Optional[str] = None
    ):
        """
        记录缓存操作
        
        Args:
            cache_type: 缓存类型
            operation: 操作类型
            key: 缓存键
        """
        self.collector.increment(
            "cache_operations_total",
            labels={
                "cache_type": cache_type,
                "operation": operation
            }
        )
    
    # ============ 系统指标 ============
    
    def record_concurrent_requests(self, count: int):
        """
        记录并发请求数
        
        Args:
            count: 并发请求数
        """
        self.collector.set_gauge("concurrent_requests", count)
    
    def record_queue_size(self, queue_name: str, size: int):
        """
        记录队列大小
        
        Args:
            queue_name: 队列名称
            size: 队列大小
        """
        self.collector.set_gauge(
            "queue_size",
            size,
            labels={"queue": queue_name}
        )
    
    # ============ 辅助方法 ============
    
    def _get_confidence_bucket(self, confidence: float) -> str:
        """
        获取置信度区间
        
        Args:
            confidence: 置信度
            
        Returns:
            置信度区间
        """
        if confidence < 0.5:
            return "0.0-0.5"
        elif confidence < 0.7:
            return "0.5-0.7"
        elif confidence < 0.9:
            return "0.7-0.9"
        else:
            return "0.9-1.0"


# 全局业务指标收集器
_business_metrics = None


def get_business_metrics() -> BusinessMetrics:
    """
    获取全局业务指标收集器
    
    Returns:
        BusinessMetrics 实例
    """
    global _business_metrics
    if _business_metrics is None:
        _business_metrics = BusinessMetrics()
    return _business_metrics


# 便捷函数
def record_http_request(endpoint: str, method: str = "POST", status_code: int = 200, duration_ms: float = 0):
    """记录 HTTP 请求"""
    metrics = get_business_metrics()
    metrics.record_http_request(endpoint, method, status_code, duration_ms)


def record_llm_call(
    model: str,
    call_type: str,
    success: bool,
    duration_ms: float,
    token_usage: Optional[Dict[str, int]] = None,
    cache_hit: bool = False
):
    """记录 LLM 调用"""
    metrics = get_business_metrics()
    metrics.record_llm_call(model, call_type, success, duration_ms, token_usage, cache_hit)


def record_skill_execution(
    business_code: str,
    skill_name: str,
    skill_type: str,
    success: bool,
    duration_ms: float,
    error_type: Optional[str] = None
):
    """记录 Skill 执行"""
    metrics = get_business_metrics()
    metrics.record_skill_execution(business_code, skill_name, skill_type, success, duration_ms, error_type)


def record_intent_recognition(
    business_code: str,
    skill_name: str,
    confidence: float,
    duration_ms: float,
    cache_hit: bool = False
):
    """记录意图识别"""
    metrics = get_business_metrics()
    metrics.record_intent_recognition(business_code, skill_name, confidence, duration_ms, cache_hit)


def record_param_extraction(
    business_code: str,
    skill_name: str,
    param_count: int,
    duration_ms: float,
    validation_success: bool
):
    """记录参数提取"""
    metrics = get_business_metrics()
    metrics.record_param_extraction(business_code, skill_name, param_count, duration_ms, validation_success)
