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


def accept_model_reply(state, reply):
    """Preserve verbatim corrections for the model; never interpret natural text as approval."""
    if not isinstance(reply,str) or not reply.strip() or len(reply)>2000:
        raise ActionError('BAD_ARGS','补充信息需要1..2000字')
    state.setdefault('reply_events',[]).append({'after_step':len(state['steps']), 'text':reply})
    state['replies'].append(reply)
    state.pop('clarification',None)
    state['pending']=None
    state['status']='running'
    state['bad_args']=0


def revise_waiting(store, state, context, reply, decision, db=None):
    """Called under task lock; approval revocation and new user input commit atomically."""
    if reply is not None and decision is not None:
        raise ActionError('BAD_ARGS','补充/更正与审批不能同时提交')
    if reply is None or state.get('agent_protocol') != 2:
        return False
    if state['status'] not in {'approval_wait','clarification_wait'}:
        raise ActionError('STATE_CONFLICT','仅等待补充或审批时可更正；已执行动作不能改写')
    from contextlib import nullcontext
    from agent_core.workflow_audit import audit_action
    with store.db.connection(write=True) if db is None else nullcontext(db) as tx:
        pending=state.get('pending')
        if pending and pending.get('action_id'):
            aid=pending['action_id']
            changed=tx.execute("UPDATE actions SET status='cancelled' WHERE action_id=? AND status='pending'",(aid,))
            if changed.rowcount!=1:
                raise ActionError('STATE_CONFLICT','动作已非待审批，不能修改')
            audit_action(tx,aid,'cancel',context)
        accept_model_reply(state,reply)
        store.save(state,db=tx)
    return True
