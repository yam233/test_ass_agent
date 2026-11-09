"""Execution assurance layer: missing params, retry, and result checks."""
import asyncio
from typing import Any, Awaitable, Callable, Dict, List


class ExecutionLayer:
    """Common execution guarantees shared by skills."""

    @staticmethod
    def find_missing_params(params: Dict[str, Any], param_schema: Dict[str, Any]) -> List[str]:
        missing = []
        for name, definition in (param_schema or {}).items():
            if not definition.get("required", False):
                continue
            value = (params or {}).get(name)
            if value in (None, "", [], {}):
                missing.append(name)
        return missing

    @staticmethod
    def build_missing_param_prompt(missing_params: List[str], param_schema: Dict[str, Any]) -> str:
        lines = ["还缺少必要参数，请补充："]
        for name in missing_params:
            desc = (param_schema.get(name, {}) or {}).get("description", "")
            lines.append(f"- {name}" + (f"：{desc}" if desc else ""))
        return "\n".join(lines)

    async def retry_async(
        self,
        operation: Callable[[], Awaitable[Any]],
        retries: int = 2,
        delay_seconds: float = 0.3,
    ) -> Any:
        last_error = None
        for attempt in range(retries + 1):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    raise
                await asyncio.sleep(delay_seconds * (attempt + 1))
        raise last_error

    @staticmethod
    def verify_result(result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"success": False, "message": "执行结果格式错误", "data": result}
        result.setdefault("success", bool(result.get("status") == "success"))
        result.setdefault("message", "执行成功" if result.get("success") else "执行失败")
        return result
