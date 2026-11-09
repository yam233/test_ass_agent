"""SQLite task checkpoints, scoped result references, and process-safe resume locks."""
import fcntl
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from agent_core.action_store import ActionError, ActionStore, canonical, scope

from agent_core.workflow_state import migrate_state, TERMINAL
from agent_core.workflow_locks import maintenance_lock
from agent_core.workflow_audit import append_event, audit_action


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_steps: int = Field(16, ge=1, le=100)
    max_tokens: int = Field(60000, ge=1, le=1000000)
    max_seconds: float = Field(120.0, gt=0, le=600)


class WorkflowStore:
    def __init__(self, path):
        self.db = ActionStore(path)
        self.lockdir = Path(str(path) + ".locks")
        self.lockdir.mkdir(parents=True, exist_ok=True)
        with self.db.connection() as db:
            db.executescript(
                """
            CREATE TABLE IF NOT EXISTS workflow_tasks (task_id TEXT PRIMARY KEY, scope TEXT NOT NULL, request_id TEXT, input TEXT NOT NULL, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, UNIQUE(scope,request_id));
            CREATE TABLE IF NOT EXISTS workflow_artifacts (fingerprint TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workflow_refs (ref_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS refs_task ON workflow_refs(task_id);
            CREATE TABLE IF NOT EXISTS workflow_control (task_id TEXT PRIMARY KEY, cancel_requested INTEGER NOT NULL DEFAULT 0);
            """
            )

        with self.db.connection() as db:
            old = "revision" not in {
                r[1] for r in db.execute("PRAGMA table_info(workflow_tasks)")
            }
            backup = Path(str(path) + ".before-v1.sqlite")
            if old and not backup.exists():
                with sqlite3.connect(backup) as destination:
                    db.backup(destination)
        with self.db.connection(write=True) as db:
            if "revision" not in {
                r[1] for r in db.execute("PRAGMA table_info(workflow_tasks)")
            }:
                db.execute(
                    "ALTER TABLE workflow_tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )
            if "created_at" not in {
                r[1] for r in db.execute("PRAGMA table_info(workflow_refs)")
            }:
                db.execute(
                    "ALTER TABLE workflow_refs ADD COLUMN created_at REAL NOT NULL DEFAULT 0"
                )

    @contextmanager
    def lock(self, task_id):
        name = hashlib.sha256(task_id.encode()).hexdigest()
        with maintenance_lock(self.db.path), open(self.lockdir / name, "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ActionError("RESOURCE_BUSY", "任务正在另一执行者运行")
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def create(self, text, context, budget, db=None):
        from agent_core.workflow_policy import resolve_policy

        policy = resolve_policy(context)
        owner = canonical(scope(context))
        request_id = context.get("request_id") or None
        with self.db.connection(write=True) if db is None else nullcontext(db) as db:
            if request_id:
                row = db.execute(
                    "SELECT payload,input FROM workflow_tasks WHERE scope=? AND request_id=?",
                    (owner, request_id),
                ).fetchone()
                if row:
                    if row["input"] != text or json.loads(row["payload"]).get(
                        "mode", "execute"
                    ) != ("dry_run" if context.get("dry_run") else "execute"):
                        raise ActionError("REQUEST_CONFLICT", "请求 ID 对应不同任务")
                    return migrate_state(json.loads(row["payload"]))
            state = {
                "revision": 0,
                "policy": policy,
                "schema_version": 1,
                "mode": "dry_run" if context.get("dry_run") else "execute",
                "task_id": str(uuid.uuid4()),
                "input": text,
                "scope": list(scope(context)),
                "budget": budget.model_dump(),
                "status": "ready",
                "stop_reason": None,
                "steps": [],
                "trace": [],
                "pending": None,
                "replies": [],
                "model_calls": 0,
                "tool_calls": 0,
                "tokens": 0,
                "reported_tokens": 0,
                "usage_complete": True,
                "elapsed": 0.0,
                "active_since": None,
                "bad_args": 0,
                "created_at": time.time(),
                "fault_id": context.get("fault_id"),
                "fault_remaining": context.get("fault_count"),
                "result": None,
            }
            db.execute(
                "INSERT INTO workflow_tasks (task_id,scope,request_id,input,payload) VALUES (?,?,?,?,?)",
                (state["task_id"], owner, request_id, text, canonical(state)),
            )
            return state

    def get(self, task_id, context, db=None):
        with self.db.connection() if db is None else nullcontext(db) as db:
            row = db.execute(
                "SELECT scope,payload,revision FROM workflow_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if not row:
            raise ActionError("TASK_NOT_FOUND", "任务不存在")
        if row["scope"] != canonical(scope(context)):
            raise ActionError("SCOPE_MISMATCH", "操作人、会话或环境不匹配")
        state = migrate_state(json.loads(row["payload"]))
        state["revision"] = row["revision"]
        with self.db.connection() as control_db:
            control = control_db.execute(
                "SELECT cancel_requested FROM workflow_control WHERE task_id=?",
                (task_id,),
            ).fetchone()
        state["cancel_requested"] = bool(control and control[0])
        return state

    def save(self, state, expected_revision=None, db=None):
        expected = (
            state.get("revision", 0) if expected_revision is None else expected_revision
        )
        value = {**state, "revision": expected + 1}
        if value["status"] in TERMINAL:
            value.setdefault("finished_at", time.time())
        with self.db.connection(write=True) if db is None else nullcontext(db) as db:
            cur = db.execute(
                "UPDATE workflow_tasks SET payload=?,revision=? WHERE task_id=? AND revision=?",
                (canonical(value), expected + 1, state["task_id"], expected),
            )
            if cur.rowcount != 1:
                exists = db.execute(
                    "SELECT 1 FROM workflow_tasks WHERE task_id=?", (state["task_id"],)
                ).fetchone()
                raise ActionError(
                    "STATE_CONFLICT" if exists else "TASK_NOT_FOUND", "状态版本冲突或任务已被重置"
                )
        state.update(value)
        return expected + 1

    def request_cancel(self, task_id, context):
        state = self.get(task_id, context)
        if state["status"] in TERMINAL:
            return state
        with self.db.connection(write=True) as db:
            db.execute(
                "INSERT INTO workflow_control VALUES (?,1) ON CONFLICT(task_id) DO UPDATE SET cancel_requested=1",
                (task_id,),
            )
            append_event(
                db,
                {
                    "event_id": task_id + ":cancel",
                    "task_id": task_id,
                    "event": "cancel",
                    "scope": list(scope(context)),
                    "operator": scope(context)[0],
                    "data": {"requested": True},
                },
            )
        return self.get(task_id, context)

    def cancel_requested(self, task_id):
        with self.db.connection() as db:
            row = db.execute(
                "SELECT cancel_requested FROM workflow_control WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return bool(row and row[0])

    def expire_approvals(self, now):
        count = 0
        with self.db.connection() as db:
            rows = list(db.execute("SELECT task_id,scope FROM workflow_tasks"))
        for row in rows:
            try:
                with self.lock(row["task_id"]), self.db.connection(write=True) as db:
                    current = db.execute(
                        "SELECT payload,revision FROM workflow_tasks WHERE task_id=?",
                        (row["task_id"],),
                    ).fetchone()
                    if current is None:
                        continue
                    state = migrate_state(json.loads(current["payload"]))
                    if state["status"] != "approval_wait":
                        continue
                    aid = state["pending"]["action_id"]
                    action = db.execute(
                        "SELECT status,expires_at FROM actions WHERE action_id=?",
                        (aid,),
                    ).fetchone()
                    if (
                        not action
                        or action["status"] != "pending"
                        or action["expires_at"] > now
                    ):
                        continue
                    db.execute(
                        "UPDATE actions SET status='expired' WHERE action_id=? AND status='pending'",
                        (aid,),
                    )
                    audit_action(db, aid, "expire")
                    state.update(
                        status="expired",
                        stop_reason="approval_expired",
                        finished_at=now,
                        revision=current["revision"] + 1,
                    )
                    db.execute(
                        "UPDATE workflow_tasks SET payload=?,revision=? WHERE task_id=?",
                        (canonical(state), state["revision"], row["task_id"]),
                    )
                    count += 1
            except ActionError as exc:
                if exc.code != "RESOURCE_BUSY":
                    raise
        return count

    def gc_refs(self, now, retention_days=7, dry_run=True):
        if retention_days < 1:
            raise ValueError("保留天数必须至少为1")
        ids = []
        with maintenance_lock(self.db.path, exclusive=True), self.db.connection(
            write=True
        ) as db:
            for row in db.execute(
                "SELECT r.ref_id,t.payload FROM workflow_refs r JOIN workflow_tasks t USING(task_id)"
            ):
                state = migrate_state(json.loads(row["payload"]))
                if (
                    state["status"] in TERMINAL - {"reconciliation_required"}
                    and state.get("finished_at", now) > 0
                    and state.get("finished_at", now) <= now - retention_days * 86400
                ):
                    ids.append(row["ref_id"])
            if not dry_run:
                db.executemany(
                    "DELETE FROM workflow_refs WHERE ref_id=?", [(rid,) for rid in ids]
                )
        return {"count": len(ids), "dry_run": dry_run, "ref_ids": ids}

    def record_artifact(self, artifact):
        fingerprint = hashlib.sha256(canonical(artifact).encode()).hexdigest()
        with self.db.connection(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO workflow_artifacts VALUES (?,?)",
                (fingerprint, canonical(artifact)),
            )
        return fingerprint

    def externalize(self, task_id, result):
        if len(canonical(result).encode()) <= 1500:
            return result
        rid = str(uuid.uuid4())
        data = result.get("data", {})
        rows = data.get("rows", [])
        with self.db.connection(write=True) as db:
            db.execute(
                "INSERT INTO workflow_refs (ref_id,task_id,payload,created_at) VALUES (?,?,?,?)",
                (rid, task_id, canonical(result), time.time()),
            )
        return {
            **{k: v for k, v in result.items() if k != "data"},
            "data": {
                "ref_id": rid,
                "row_count": len(rows),
                "schema": list(rows[0]) if rows and isinstance(rows[0], dict) else [],
                "sample_3": rows[:3],
                **{
                    k: v
                    for k, v in data.items()
                    if k in {"total_quantity", "batch_id", "actual", "expected"}
                },
            },
        }

    def read_ref(self, task_id, args, context):
        self.get(task_id, context)
        with self.db.connection() as db:
            row = db.execute(
                "SELECT task_id,payload FROM workflow_refs WHERE ref_id=?",
                (args["ref_id"],),
            ).fetchone()
        if not row or row["task_id"] != task_id:
            raise ActionError("NOT_FOUND", "引用不存在或不属于此任务")
        payload = json.loads(row["payload"])
        rows = payload.get("data", {}).get("rows")
        if rows is None:
            rows = [payload]
        start = args.get("offset", 0)
        limit = args.get("limit", 20)
        from agent_core.workflow_contracts import Ref, failure

        values = Ref(**args).model_dump()
        start, limit = values["offset"], values["limit"]
        page = []

        def response():
            end = start + len(page)
            return {
                "success": True,
                "status": "success",
                "code": "OK",
                "data": {
                    "rows": page,
                    "row_count": len(rows),
                    "offset": start,
                    "returned_count": len(page),
                    "next_offset": end if end < len(rows) else None,
                    "truncated": end < len(rows),
                },
            }

        for item in rows[start : start + limit]:
            page.append(item)
            if len(canonical(response()).encode()) > 16384:
                page.pop()
                if not page:
                    return failure("ROW_TOO_LARGE", "单行超过引用页大小限制，请查询更小字段集", "read_ref")
                break
        return response()
