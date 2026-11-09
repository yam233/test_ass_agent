"""
统一异常和错误码

提供统一的错误码体系和异常处理机制，便于问题排查和监控。

设计原则：
1. 错误码分类清晰（通用/业务/系统）
2. 异常信息结构化（code + message + data）
3. 支持链路追踪（trace_id）
4. 便于监控和告警
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ErrorCode:
    """
    统一错误码
    
    格式：5位数字
    - 00xxx: 通用错误
    - 10xxx: 业务错误
    - 20xxx: LLM 相关错误
    - 30xxx: MCP 相关错误
    - 40xxx: 缓存/存储错误
    - 50xxx: 系统错误
    """
    
    # ========== 通用错误 (00xxx) ==========
    SUCCESS = "00000"
    INVALID_PARAM = "00001"
    TIMEOUT_ERROR = "00002"
    RATE_LIMIT_ERROR = "00003"
    PERMISSION_DENIED = "00004"
    
    # ========== 业务错误 (10xxx) ==========
    ENV_NOT_ALLOWED = "10001"
    SKILL_NOT_FOUND = "10002"
    INTENT_NOT_FOUND = "10003"
    PARAM_MISSING = "10004"
    PARAM_INVALID = "10005"
    IDEMPOTENT_ERROR = "10006"
    BUSINESS_RULE_ERROR = "10007"
    
    # ========== LLM 相关错误 (20xxx) ==========
    LLM_CALL_FAILED = "20001"
    LLM_TIMEOUT = "20002"
    LLM_PARSE_ERROR = "20003"
    LLM_QUOTA_EXCEEDED = "20004"
    LLM_INVALID_RESPONSE = "20005"
    
    # ========== MCP 相关错误 (30xxx) ==========
    MCP_CALL_FAILED = "30001"
    MCP_TIMEOUT = "30002"
    MCP_CONNECTION_ERROR = "30003"
    MCP_INVALID_RESPONSE = "30004"
    MCP_SERVER_ERROR = "30005"
    
    # ========== 缓存/存储错误 (40xxx) ==========
    CACHE_ERROR = "40001"
    REDIS_ERROR = "40002"
    DATABASE_ERROR = "40003"
    
    # ========== 系统错误 (50xxx) ==========
    SYSTEM_ERROR = "50001"
    CONFIG_ERROR = "50002"
    INTERNAL_ERROR = "50003"
    UNKNOWN_ERROR = "50099"


class BusinessError(Exception):
    """
    业务异常基类
    
    所有业务异常都应该继承此类，提供统一的错误信息结构。
    
    Attributes:
        code: 错误码
        message: 错误信息
        data: 附加数据
        trace_id: 追踪ID（可选）
    """
    
    def __init__(
        self,
        code: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None
    ):
        """
        初始化业务异常
        
        Args:
            code: 错误码
            message: 错误信息
            data: 附加数据
            trace_id: 追踪ID
        """
        self.code = code
        self.message = message
        self.data = data or {}
        self.trace_id = trace_id
        
        # 构造异常消息
        error_msg = f"[{code}] {message}"
        if trace_id:
            error_msg += f" (trace_id: {trace_id})"
        
        super().__init__(error_msg)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式
        
        Returns:
            字典格式的错误信息
        """
        result = {
            "code": self.code,
            "message": self.message,
            "data": self.data
        }
        
        if self.trace_id:
            result["trace_id"] = self.trace_id
        
        return result


# ========== 具体异常类 ==========

class InvalidParamError(BusinessError):
    """参数错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.INVALID_PARAM, message, data, trace_id)


class TimeoutError(BusinessError):
    """超时错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.TIMEOUT_ERROR, message, data, trace_id)


class EnvNotAllowedError(BusinessError):
    """环境不允许错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.ENV_NOT_ALLOWED, message, data, trace_id)


class SkillNotFoundError(BusinessError):
    """Skill 未找到错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.SKILL_NOT_FOUND, message, data, trace_id)


class IntentNotFoundError(BusinessError):
    """意图未找到错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.INTENT_NOT_FOUND, message, data, trace_id)


class ParamMissingError(BusinessError):
    """参数缺失错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.PARAM_MISSING, message, data, trace_id)


class LLMCallError(BusinessError):
    """LLM 调用错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.LLM_CALL_FAILED, message, data, trace_id)


class MCPCallError(BusinessError):
    """MCP 调用错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.MCP_CALL_FAILED, message, data, trace_id)


class IdempotentError(BusinessError):
    """幂等性错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.IDEMPOTENT_ERROR, message, data, trace_id)


class SystemError(BusinessError):
    """系统错误"""
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
        super().__init__(ErrorCode.SYSTEM_ERROR, message, data, trace_id)


# ========== 便捷函数 ==========

def raise_error(
    code: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None
):
    """
    抛出业务异常
    
    Args:
        code: 错误码
        message: 错误信息
        data: 附加数据
        trace_id: 追踪ID
        
    Raises:
        BusinessError: 业务异常
    """
    raise BusinessError(code, message, data, trace_id)


def get_error_message(code: str) -> str:
    """
    获取错误码对应的默认错误信息
    
    Args:
        code: 错误码
        
    Returns:
        默认错误信息
    """
    error_messages = {
        ErrorCode.SUCCESS: "成功",
        ErrorCode.INVALID_PARAM: "参数错误",
        ErrorCode.TIMEOUT_ERROR: "请求超时",
        ErrorCode.RATE_LIMIT_ERROR: "请求频率超限",
        ErrorCode.PERMISSION_DENIED: "权限不足",
        
        ErrorCode.ENV_NOT_ALLOWED: "环境不允许",
        ErrorCode.SKILL_NOT_FOUND: "Skill 未找到",
        ErrorCode.INTENT_NOT_FOUND: "意图识别失败",
        ErrorCode.PARAM_MISSING: "参数缺失",
        ErrorCode.PARAM_INVALID: "参数无效",
        ErrorCode.IDEMPOTENT_ERROR: "幂等性错误",
        ErrorCode.BUSINESS_RULE_ERROR: "业务规则错误",
        
        ErrorCode.LLM_CALL_FAILED: "LLM 调用失败",
        ErrorCode.LLM_TIMEOUT: "LLM 调用超时",
        ErrorCode.LLM_PARSE_ERROR: "LLM 响应解析失败",
        ErrorCode.LLM_QUOTA_EXCEEDED: "LLM 配额超限",
        ErrorCode.LLM_INVALID_RESPONSE: "LLM 响应无效",
        
        ErrorCode.MCP_CALL_FAILED: "MCP 调用失败",
        ErrorCode.MCP_TIMEOUT: "MCP 调用超时",
        ErrorCode.MCP_CONNECTION_ERROR: "MCP 连接失败",
        ErrorCode.MCP_INVALID_RESPONSE: "MCP 响应无效",
        ErrorCode.MCP_SERVER_ERROR: "MCP 服务器错误",
        
        ErrorCode.CACHE_ERROR: "缓存错误",
        ErrorCode.REDIS_ERROR: "Redis 错误",
        ErrorCode.DATABASE_ERROR: "数据库错误",
        
        ErrorCode.SYSTEM_ERROR: "系统错误",
        ErrorCode.CONFIG_ERROR: "配置错误",
        ErrorCode.INTERNAL_ERROR: "内部错误",
        ErrorCode.UNKNOWN_ERROR: "未知错误",
    }
    
    return error_messages.get(code, "未知错误")
