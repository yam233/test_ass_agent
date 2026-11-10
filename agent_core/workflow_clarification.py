"""Persist missing fields and accept explicit, schema-checked user supplements."""
import json
import re
from pydantic import ValidationError
from agent_core.action_store import ActionError
from agent_core.workflow_contracts import SPECS, WRITES, normalize, failure


def missing_fields(tool, error):
    if tool not in SPECS or not isinstance(error, ValidationError):
        return []
    errors = error.errors()
    if not errors or any(e["type"] != "missing" or len(e["loc"]) != 1 for e in errors):
        return []
    return [e["loc"][0] for e in errors]


def accept_reply(state, reply):
    pending = state.get("clarification")
    if not pending:
        state["replies"].append(reply)
        state["status"] = "running"
        return
    fields = pending["missing_fields"]
    try:
        supplied = json.loads(reply)
    except (ValueError, TypeError):
        supplied = reply.strip()
    if not isinstance(supplied, dict):
        if len(fields) != 1:
            state["result"] = {
                **failure("BAD_ARGS", "请用 JSON 对象补齐所列字段"),
                "missing_fields": fields,
            }
            return
        name = fields[0]
        if name in {"quantity", "user_id", "gift_id"} and isinstance(supplied, str):
            match = re.fullmatch(r"([+-]?\d+)\s*个?", supplied)
            if match:
                supplied = int(match[1])
        supplied = {name: supplied}
    if set(supplied) - set(fields):
        raise ActionError("BAD_ARGS", "补充信息只能填写缺失字段；修改已有参数请新建任务")
    merged = {**pending["args"], **supplied}
    try:
        args = normalize(pending["tool"], merged)
    except (ValueError, TypeError) as exc:
        state["result"] = {**failure("BAD_ARGS", str(exc)), "missing_fields": fields}
        return
    state["replies"].append(reply)
    state["pending"] = {
        "tool": pending["tool"],
        "args": args,
        "attempts": 0,
        "action_id": None,
        "phase": "prepare" if pending["tool"] in WRITES else "execute",
    }
    state.pop("clarification")
    state["status"] = "running"
