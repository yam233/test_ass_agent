"""Permission checks for LangGraph tools."""
from dataclasses import dataclass
from typing import Any, Dict

from agent_core.langgraph_agent.common import ErrorCode


OPEN_ACTIONS = {"query", "metadata", "export", "script_read", "script_scan", "chat"}
CONFIRM_ACTIONS = {"write", "execute", "script_execute"}


@dataclass
class PermissionDecision:
    allowed: bool
    need_confirm: bool = False
    message: str = "ok"
    code: str = ErrorCode.OK.value


class PermissionGuard:
    """Global policy: reads are open, writes/execution require confirmation."""

    def evaluate(self, action: str, context: Dict[str, Any] | None = None) -> PermissionDecision:
        context = context or {}
        env = str(context.get("env") or context.get("environment") or "uat").lower()
        confirmed = bool(context.get("execute_confirmed") or context.get("approved"))
        allowed_tools = context.get("allowed_tools")
        tool_name = context.get("tool_name")

        if allowed_tools is not None and tool_name and tool_name not in allowed_tools:
            return PermissionDecision(
                False,
                False,
                f"当前操作人无权限使用工具: {tool_name}",
                ErrorCode.PERMISSION_DENIED.value,
            )

        if action in OPEN_ACTIONS:
            return PermissionDecision(True)
        if action in CONFIRM_ACTIONS:
            if env == "prod":
                return PermissionDecision(False, False, "生产环境写入/执行操作被全局拦截", ErrorCode.PERMISSION_DENIED.value)
            if not confirmed:
                return PermissionDecision(True, True, "该操作需要管理员二次确认", ErrorCode.CONFIRM_REQUIRED.value)
            return PermissionDecision(True)
        return PermissionDecision(False, False, f"未知权限动作: {action}", ErrorCode.PERMISSION_DENIED.value)


def require_permission(action: str):
    def decorator(fn):
        def wrapper(self, *args, **kwargs):
            context = kwargs.get("context") or {}
            decision = PermissionGuard().evaluate(action, context)
            if not decision.allowed or decision.need_confirm:
                return {
                    "success": False,
                    "status": "blocked",
                    "code": decision.code,
                    "message": decision.message,
                    "data": {"need_confirm": decision.need_confirm},
                }
            return fn(self, *args, **kwargs)

        return wrapper

    return decorator
