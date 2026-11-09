"""Small helpers for consistent Agent result status."""
from typing import Any, Dict, Optional


STATUS_SUCCESS = "success"
STATUS_PARTIAL_SUCCESS = "partial_success"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"


def status_from_counts(success_count: int, failed_count: int) -> str:
    if failed_count == 0:
        return STATUS_SUCCESS
    if success_count > 0:
        return STATUS_PARTIAL_SUCCESS
    return STATUS_FAILED


def is_success_status(status: Optional[str]) -> bool:
    return status == STATUS_SUCCESS


def build_blocked_result(
    message: str,
    skill_name: str,
    intent: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "success": False,
        "status": STATUS_BLOCKED,
        "message": message,
        "error": None,
        "intent": intent,
        "params": params,
        "skill_name": skill_name,
        "blocked": True,
    }
    if data is not None:
        payload["data"] = data
    return payload
