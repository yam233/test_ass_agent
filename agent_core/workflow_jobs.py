"""Persistent single-host jobs; task creation and approval enqueue are atomic."""
import json
import time
from agent_core.action_store import ActionError, canonical, scope
from agent_core.workflow_store import WorkflowStore
from agent_core.workflow_state import TERMINAL
from agent_core.workflow_policy import resolve_policy, check_tool, check_cleanup_impact
from agent_core.workflow_audit import audit_action


class JobStore:
    def __init__(self, path, capacity=100):
        if capacity < 1:
            raise ValueError("queue capacity must be positive")
        self.store = WorkflowStore(path)
        self.capacity = capacity
        with self.store.db.connection(write=True) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS workflow_jobs (
                task_id TEXT PRIMARY KEY,status TEXT NOT NULL,context TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 0,started_at REAL,pid INTEGER,last_error TEXT)"""
            )

    def _enqueue(self, db, state, context):
        row = db.execute(
            "SELECT * FROM workflow_jobs WHERE task_id=?", (state["task_id"],)
        ).fetchone()
        if row and row["status"] in {"queued", "running"}:
            return dict(row)
        if state["status"] in TERMINAL or state["status"] in {
            "approval_wait",
            "clarification_wait",
        }:
            return None
        if (
            db.execute(
                "SELECT count(*) FROM workflow_jobs WHERE status='queued'"
            ).fetchone()[0]
            >= self.capacity
        ):
            raise ActionError("QUEUE_FULL", "任务队列已满")
        # Persist only execution controls, never caller-supplied credentials.
        keys = {
            "operator",
            "session_id",
            "env",
            "environment",
            "allowed_tools",
            "dry_run",
        }
        saved = {k: v for k, v in context.items() if k in keys}
        db.execute(
            """INSERT INTO workflow_jobs(task_id,status,context,generation) VALUES (?,'queued',?,1)
            ON CONFLICT(task_id) DO UPDATE SET status='queued',context=excluded.context,generation=workflow_jobs.generation+1,pid=NULL""",
            (state["task_id"], canonical(saved)),
        )
        return {"task_id": state["task_id"], "status": "queued"}

    def enqueue(self, task_id, context):
        with self.store.db.connection(write=True) as db:
            return self._enqueue(db, self.store.get(task_id, context, db), context)

    def submit(self, text, context, budget):
        from agent_core.workflow import WorkflowRuntime

        WorkflowRuntime._check_context(context)
        if not isinstance(text, str) or not text.strip() or len(text) > 10000:
            raise ValueError("输入不能为空或超过10000字")
        with self.store.db.connection(write=True) as db:
            state = self.store.create(text, context, budget, db)
            self._enqueue(db, state, context)
        return state

    def resume(
        self,
        task_id,
        context,
        action_id=None,
        decision=None,
        reply=None,
        confirm_effect=None,
        snapshot_hash=None,
    ):
        with self.store.lock(task_id), self.store.db.connection(write=True) as db:
            state = self.store.get(task_id, context, db)
            if state["status"] in TERMINAL:
                return state
            policy = resolve_policy(context, state.get("policy"))
            effective = {
                **context,
                "allowed_tools": policy["allowed_tools"],
                "policy_version": policy["policy_version"],
                "confirm_effect": confirm_effect,
                "snapshot_hash": snapshot_hash,
            }
            if state["status"] == "approval_wait":
                if decision is None:
                    return state
                if action_id != state["pending"]["action_id"]:
                    raise ActionError("APPROVAL_MISMATCH", "必须批准当前动作 ID")
                if decision not in {"approve", "deny"}:
                    raise ActionError("BAD_ARGS", "decision 必须为 approve/deny")
                if decision == "deny":
                    self.store.db.deny(action_id, effective, db)
                    state.update(
                        status="denied", stop_reason="denied", finished_at=time.time()
                    )
                else:
                    policy = check_tool(state["pending"]["tool"], effective, policy)
                    check_cleanup_impact(
                        state["pending"]["tool"], state["pending"]["args"], policy, db
                    )
                    self.store.db.approve(action_id, effective, db)
                    state["pending"]["phase"] = "execute"
                    state["status"] = "running"
            elif decision is not None:
                raise ActionError("APPROVAL_INVALID", "当前没有待批动作")
            if state["status"] == "clarification_wait":
                if not isinstance(reply, str) or not reply or len(reply) > 2000:
                    raise ActionError("BAD_ARGS", "需要1..2000字补充信息")
                state["replies"].append(reply)
                state["status"] = "running"
            state["policy"] = policy
            self.store.save(state, db=db)
            # A prior worker may have returned its wait state but not yet exited.
            db.execute(
                "UPDATE workflow_jobs SET status='waiting',generation=generation+1 WHERE task_id=?",
                (task_id,),
            )
            self._enqueue(db, state, effective)
        return state

    def cancel(self, task_id, context):
        state = self.store.request_cancel(task_id, context)
        if state["status"] in TERMINAL:
            return state
        try:
            with self.store.lock(task_id), self.store.db.connection(write=True) as db:
                state = self.store.get(task_id, context, db)
                # A pending executed write must first be reconciled by a worker.
                if state["status"] in {
                    "ready",
                    "approval_wait",
                    "clarification_wait",
                } and (
                    not state.get("pending")
                    or state["pending"].get("phase") != "execute"
                ):
                    if state.get("pending") and state["pending"].get("action_id"):
                        aid = state["pending"]["action_id"]
                        db.execute(
                            "UPDATE actions SET status='cancelled' WHERE action_id=? AND status IN ('pending','approved')",
                            (aid,),
                        )
                        audit_action(db, aid, "cancel", context)
                    state.update(
                        status="cancelled",
                        stop_reason="cancelled",
                        finished_at=time.time(),
                    )
                    self.store.save(state, db=db)
                    db.execute(
                        "UPDATE workflow_jobs SET status='done',generation=generation+1 WHERE task_id=?",
                        (task_id,),
                    )
        except ActionError as exc:
            if exc.code != "RESOURCE_BUSY":
                raise
        return self.store.get(task_id, context)
