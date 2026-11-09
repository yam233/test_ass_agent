"""Safety and permission layer for Agent execution."""
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SafetyDecision:
    allowed: bool
    need_confirm: bool = False
    reason: str = ""
    policy: str = "default"


class SafetyLayer:
    """
    Central permission policy.

    Defaults:
    - query/meta skills are open
    - execute/script/write skills require admin confirmation
    - prod execute is blocked
    """

    OPEN_TYPES = {"query", "metadata", "meta", "analysis"}
    WRITE_ACTIONS = {"execute", "write", "script_execute", "delete", "update", "insert"}

    def __init__(self, local_config=None, framework_config: Optional[Dict[str, Any]] = None):
        self.local_config = local_config
        self.framework_config = framework_config or {}

    def evaluate(
        self,
        skill_config: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> SafetyDecision:
        context = context or {}
        skill_type = skill_config.get("skill_type") or skill_config.get("type") or "query"
        risk_level = skill_config.get("risk_level", "low")
        operator = context.get("operator", "")
        env = context.get("env", "uat")

        if env == "prod" and skill_type in self.WRITE_ACTIONS:
            return SafetyDecision(False, False, "生产环境禁止执行写操作", "env_block")

        if skill_type in self.OPEN_TYPES:
            return SafetyDecision(True, False, "查询/元信息类操作开放", "open_read")

        if context.get("execute_confirmed") or context.get("skip_execute_confirm"):
            return SafetyDecision(True, False, "已确认执行", "confirmed")

        policy = self._operator_policy()
        admins = set(policy.get("admins", []))
        confirm_mode = policy.get("write_confirm_mode", "admin_or_explicit_confirm")

        if confirm_mode == "admin_only" and operator not in admins:
            return SafetyDecision(False, False, f"操作人 {operator} 不是管理员", "admin_only")

        return SafetyDecision(
            True,
            True,
            f"{skill_type} 操作风险等级 {risk_level}，需要二次确认",
            "confirm_required"
        )

    def _operator_policy(self) -> Dict[str, Any]:
        if self.local_config:
            policy = self.local_config.get_operator_policy()
            if policy:
                return policy
        return {
            "admins": [],
            "write_confirm_mode": "admin_or_explicit_confirm"
        }
