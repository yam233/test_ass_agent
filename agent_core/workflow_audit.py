"""Append-only local audit records written in the caller's transaction."""
import hashlib
import json
import time
import uuid


def initialize(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS workflow_audit (
        event_id TEXT PRIMARY KEY, task_id TEXT, action_id TEXT, event TEXT NOT NULL,
        scope TEXT NOT NULL, ts REAL NOT NULL, payload TEXT NOT NULL)"""
    )
    db.execute("CREATE INDEX IF NOT EXISTS audit_task ON workflow_audit(task_id,ts)")


def append_event(db, event: dict) -> None:
    value = {
        **event,
        "ts": event.get("ts", time.time()),
        "event_id": event.get("event_id", str(uuid.uuid4())),
    }
    db.execute(
        "INSERT OR IGNORE INTO workflow_audit VALUES (?,?,?,?,?,?,?)",
        (
            value["event_id"],
            value.get("task_id"),
            value.get("action_id"),
            value["event"],
            json.dumps(value["scope"], ensure_ascii=False, separators=(",", ":")),
            value["ts"],
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        ),
    )


def audit_action(db, action_id, event, context=None, data=None):
    row = db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
    if not row:
        return
    context = context or {}
    request = row["request_id"] or ""
    task_id = request.rsplit(":", 1)[0] if ":" in request else None
    previous = db.execute(
        "SELECT payload FROM workflow_audit WHERE event_id=?", (action_id + ":prepare",)
    ).fetchone()
    version = context.get("policy_version") or (
        json.loads(previous[0]).get("policy_version") if previous else None
    )
    append_event(
        db,
        {
            "event_id": action_id + ":" + event,
            "task_id": task_id,
            "action_id": action_id,
            "event": event,
            "operator": row["operator"],
            "scope": [row["operator"], row["session_id"], row["env"]],
            "args_hash": hashlib.sha256(row["args_json"].encode()).hexdigest(),
            "policy_version": version or "legacy-local",
            "data": data or {},
        },
    )
