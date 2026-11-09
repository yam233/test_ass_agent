"""Common result, validation, tracing, and retry helpers for the LangGraph agent."""
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, Field, ValidationError

try:  # pragma: no cover - optional dependency behavior
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
except Exception:  # pragma: no cover
    retry = None
    retry_if_exception_type = None
    stop_after_attempt = None
    wait_fixed = None


@dataclass
class ToolResult:
    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    status: str = "success"
    tool_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "tool_name": self.tool_name,
            "data": self.data,
        }


class ErrorCode(str, Enum):
    OK = "OK"
    NEED_MORE_INFO = "NEED_MORE_INFO"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    LLM_ERROR = "LLM_ERROR"
    RESOURCE_BUSY = "RESOURCE_BUSY"
    TIMEOUT = "TIMEOUT"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class AgentError(Exception):
    def __init__(self, code: ErrorCode, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class IntentPayload(BaseModel):
    intent: str = Field(default="unclear")
    tool_name: str = Field(default="")
    params: Dict[str, Any] = Field(default_factory=dict)
    is_chat: bool = Field(default=False)


def ensure_request_id(context: Dict[str, Any]) -> str:
    request_id = context.get("request_id") or str(uuid.uuid4())
    context["request_id"] = request_id
    return request_id


def start_trace(request_id: str) -> Dict[str, Any]:
    return {"request_id": request_id, "nodes": [], "started_at": time.time()}


def record_trace(trace: Dict[str, Any], node: str, started_at: float, success: bool = True, **extra: Any) -> None:
    trace.setdefault("nodes", []).append({
        "node": node,
        "duration_ms": round((time.time() - started_at) * 1000, 2),
        "success": success,
        **{k: v for k, v in extra.items() if v is not None},
    })


def validate_payload(model: type[BaseModel], data: Dict[str, Any]) -> tuple[bool, Dict[str, Any], str]:
    try:
        parsed = model(**(data or {}))
    except ValidationError as exc:
        return False, {}, str(exc)
    if hasattr(parsed, "model_dump"):
        return True, parsed.model_dump(), "ok"
    return True, parsed.dict(), "ok"


def format_result(result: Any, tool_name: str = "") -> Dict[str, Any]:
    if isinstance(result, ToolResult):
        payload = result.to_dict()
    elif isinstance(result, dict):
        payload = dict(result)
        payload.setdefault("success", bool(payload.get("success", False)))
        payload.setdefault("status", "success" if payload["success"] else "failed")
        payload.setdefault("code", ErrorCode.OK.value if payload["success"] else ErrorCode.SYSTEM_ERROR.value)
        payload.setdefault("message", "")
        payload.setdefault("data", {})
    else:
        payload = {
            "success": True,
            "status": "success",
            "code": ErrorCode.OK.value,
            "message": str(result),
            "data": {},
        }
    if tool_name:
        payload.setdefault("tool_name", tool_name)
    return payload


def error_result(
    code: ErrorCode | str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    status: str = "failed",
    request_id: Optional[str] = None,
    tool_name: str = "",
) -> Dict[str, Any]:
    return {
        "success": False,
        "status": status,
        "code": code.value if isinstance(code, ErrorCode) else code,
        "message": message,
        "data": data or {},
        "request_id": request_id,
        "tool_name": tool_name,
    }


def attach_trace(result: Dict[str, Any], trace: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    result["request_id"] = request_id
    result.setdefault("data", {})
    if isinstance(result["data"], dict):
        result["data"].setdefault("trace", trace)
    return result


def with_retry(attempts: int = 2, wait_seconds: float = 0.2) -> Callable:
    if retry is not None:
        return retry(
            stop=stop_after_attempt(attempts),
            wait=wait_fixed(wait_seconds),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )

    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any):
            last_error: Optional[Exception] = None
            for _ in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # pragma: no cover - fallback only
                    last_error = exc
            raise last_error  # type: ignore[misc]

        return wrapper

    return decorator
