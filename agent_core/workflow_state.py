"""Versioned checkpoint loading; unknown formats never execute writes."""
from copy import deepcopy
from agent_core.action_store import ActionError

SCHEMA_VERSION = 1
TERMINAL = {
    "completed",
    "failed",
    "denied",
    "partial",
    "planned",
    "cancelled",
    "expired",
    "reconciliation_required",
}


def migrate_state(payload: dict) -> dict:
    state = deepcopy(payload)
    version = state.get("schema_version", 0)
    if type(version) is not int or version not in {0, SCHEMA_VERSION}:
        raise ActionError("STATE_VERSION", "不支持的任务状态版本")
    if version == 0:
        state["schema_version"] = SCHEMA_VERSION
        state.setdefault("mode", "execute")
    if state.get("mode") not in {"execute", "dry_run"}:
        raise ActionError("STATE_VERSION", "任务模式版本无效")
    return state
