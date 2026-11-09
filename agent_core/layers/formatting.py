"""Unified result formatting for Agent responses."""
from typing import Any, Dict


class FormattingLayer:
    """Normalize outbound Agent result shape."""

    @staticmethod
    def normalize(result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {
                "success": False,
                "status": "failed",
                "message": "系统返回了意外的数据格式",
                "data": result,
                "skill_name": "unknown"
            }

        status = result.get("status")
        if not status:
            status = "success" if result.get("success") else "failed"
            result["status"] = status

        result.setdefault("success", status == "success")
        result.setdefault("message", "执行成功" if result.get("success") else "执行失败")
        result.setdefault("data", {})
        return result

    @staticmethod
    def confirmation_plan(skill_config: Dict[str, Any], params: Dict[str, Any], reason: str) -> str:
        display_name = skill_config.get("display_name") or skill_config.get("skill_name")
        risk_level = skill_config.get("risk_level", "medium")
        param_lines = [
            f"- {key}: {value}"
            for key, value in (params or {}).items()
            if value not in (None, "", [], {})
        ]
        params_text = "\n".join(param_lines) if param_lines else "- 无参数"
        return (
            f"检测到执行类操作：{display_name}\n"
            f"风险等级：{risk_level}\n"
            f"拦截原因：{reason}\n\n"
            f"待执行参数：\n{params_text}\n\n"
            "请回复“确认执行”继续，或回复“取消”放弃。"
        )
