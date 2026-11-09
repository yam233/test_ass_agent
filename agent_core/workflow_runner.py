"""Single-host durable scheduler with a bounded subprocess execution pool."""
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from agent_core.action_store import ActionError, canonical
from agent_core.workflow_jobs import JobStore
from agent_core.workflow_state import TERMINAL


class WorkflowRunner:
    def __init__(self, path, workers=2, capacity=100, tool_timeout=5.0):
        if not 1 <= workers <= 8:
            raise ValueError("workers must be 1..8")
        self.jobs = JobStore(path, capacity)
        self.workers = workers
        self.tool_timeout = tool_timeout
        self.active = {}
        self.max_observed = 0
        self.accepting = True
        self._task = None
        self._lock = None

    async def start(self):
        if self._task is not None:
            return
        lock = open(self.jobs.store.lockdir / "scheduler.lock", "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise ActionError("RESOURCE_BUSY", "当前数据库已有调度器")
        self._lock = lock
        self.accepting = True
        try:
            await asyncio.to_thread(self.recover)
            await asyncio.to_thread(self.jobs.store.expire_approvals, time.time())
        except BaseException:
            lock.close()
            self._lock = None
            raise
        self._task = asyncio.create_task(self._loop())

    def recover(self):
        with self.jobs.store.db.connection() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM workflow_jobs WHERE status='running'"
                )
            ]
        for job in rows:
            if job["task_id"] in self.active:
                continue
            try:
                with self.jobs.store.lock(
                    job["task_id"]
                ), self.jobs.store.db.connection(write=True) as db:
                    current = db.execute(
                        "SELECT * FROM workflow_jobs WHERE task_id=?", (job["task_id"],)
                    ).fetchone()
                    if not current or current["generation"] != job["generation"]:
                        continue
                    ctx = json.loads(job["context"])
                    state = self.jobs.store.get(job["task_id"], ctx, db)
                    if state["status"] in TERMINAL:
                        status = "done"
                    elif state["status"] in {"approval_wait", "clarification_wait"}:
                        status = "waiting"
                        pending = state.get("pending") or {}
                        if pending.get("action_id"):
                            action = db.execute(
                                "SELECT status FROM actions WHERE action_id=?",
                                (pending["action_id"],),
                            ).fetchone()
                            if action and action[0] in {
                                "approved",
                                "running",
                                "retryable",
                                "unknown",
                                "success",
                                "partial_success",
                            }:
                                state["status"] = "running"
                                pending["phase"] = "execute"
                                status = "queued"
                    else:
                        status = "queued"
                    if status == "queued":
                        if state.get("active_since") is None and job.get("started_at"):
                            state["elapsed"] += max(0, time.time() - job["started_at"])
                            state["usage_complete"] = False
                        self.jobs.store.save(state, db=db)
                    db.execute(
                        "UPDATE workflow_jobs SET status=?,pid=NULL,generation=generation+1 WHERE task_id=? AND generation=?",
                        (status, job["task_id"], job["generation"]),
                    )
            except ActionError as exc:
                if exc.code not in {"RESOURCE_BUSY", "STATE_CONFLICT"}:
                    raise
        # Tasks left by direct SDK calls are only recovered when no executor holds their lock.
        with self.jobs.store.db.connection() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT t.task_id,t.scope,t.payload FROM workflow_tasks t LEFT JOIN workflow_jobs j USING(task_id) WHERE j.task_id IS NULL"
                )
            ]
        for row in rows:
            state = json.loads(row["payload"])
            if state["status"] not in {"ready", "running"}:
                continue
            owner, session, env = json.loads(row["scope"])
            ctx = {"operator": owner, "session_id": session, "env": env}
            try:
                with self.jobs.store.lock(row["task_id"]):
                    self.jobs.enqueue(row["task_id"], ctx)
            except ActionError as exc:
                if exc.code not in {"RESOURCE_BUSY", "QUEUE_FULL"}:
                    raise

    def _reap(self):
        for task_id, (process, generation) in list(self.active.items()):
            if process.poll() is None:
                continue
            process.wait()
            del self.active[task_id]
            # Keep a crashed running job for recover(), which checks its OS lock.
            with self.jobs.store.db.connection(write=True) as db:
                row = db.execute(
                    "SELECT context,generation FROM workflow_jobs WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if not row or row["generation"] != generation:
                    continue
                state = self.jobs.store.get(task_id, json.loads(row["context"]), db)
                status = (
                    "done"
                    if state["status"] in TERMINAL
                    else "waiting"
                    if state["status"] in {"approval_wait", "clarification_wait"}
                    else "running"
                )
                db.execute(
                    "UPDATE workflow_jobs SET status=?,last_error=?,pid=NULL WHERE task_id=? AND generation=?",
                    (
                        status,
                        None
                        if process.returncode == 0
                        else "worker_exit:" + str(process.returncode),
                        task_id,
                        generation,
                    ),
                )

    def _dispatch(self):
        while self.accepting and len(self.active) < self.workers:
            with self.jobs.store.db.connection(write=True) as db:
                row = db.execute(
                    "SELECT task_id,generation FROM workflow_jobs WHERE status='queued' ORDER BY rowid LIMIT 1"
                ).fetchone()
                if not row:
                    return
                task_id = row["task_id"]
                generation = row["generation"] + 1
                db.execute(
                    "UPDATE workflow_jobs SET status='running',generation=?,started_at=? WHERE task_id=? AND status='queued'",
                    (generation, time.time(), task_id),
                )
            command = [
                sys.executable,
                "-m",
                "agent_core.workflow_runner",
                "--worker",
                "--db",
                str(Path(self.jobs.store.db.path).resolve()),
                "--task-id",
                task_id,
                "--tool-timeout",
                str(self.tool_timeout),
            ]
            try:
                process = subprocess.Popen(
                    command,
                    cwd=Path(__file__).resolve().parents[1],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError:
                with self.jobs.store.db.connection(write=True) as db:
                    db.execute(
                        "UPDATE workflow_jobs SET status='queued' WHERE task_id=? AND generation=?",
                        (task_id, generation),
                    )
                raise
            self.active[task_id] = (process, generation)
            self.max_observed = max(self.max_observed, len(self.active))
            with self.jobs.store.db.connection(write=True) as db:
                db.execute(
                    "UPDATE workflow_jobs SET pid=? WHERE task_id=? AND generation=?",
                    (process.pid, task_id, generation),
                )

    async def _loop(self):
        last_maintenance = 0
        while self.accepting or self.active:
            await asyncio.to_thread(self._reap)
            if self.accepting:
                await asyncio.to_thread(self.recover)
                await asyncio.to_thread(self._dispatch)
                if time.monotonic() - last_maintenance > 30:
                    await asyncio.to_thread(
                        self.jobs.store.expire_approvals, time.time()
                    )
                    last_maintenance = time.monotonic()
            await asyncio.sleep(0.025)

    async def wait(self, task_id, context):
        while True:
            state = await asyncio.to_thread(self.jobs.store.get, task_id, context)
            if state["status"] in TERMINAL or state["status"] in {
                "approval_wait",
                "clarification_wait",
            }:
                # Release the execution slot before callers immediately resume/restart.
                if task_id in self.active:
                    await asyncio.sleep(0.025)
                    continue
                return state
            if self._task is not None and self._task.done():
                error = self._task.exception()
                raise RuntimeError("scheduler stopped") from error
            await asyncio.sleep(0.025)

    async def stop(self, grace=10.0):
        self.accepting = False
        loop_error = None
        try:
            if self._task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), timeout=grace)
                except asyncio.TimeoutError:
                    pass
                except Exception as exc:
                    loop_error = exc
            for process, _ in list(self.active.values()):
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            end = time.monotonic() + 1
            while self.active and time.monotonic() < end:
                # Only the scheduler loop mutates the active pool while alive.
                await asyncio.sleep(0.025)
            for process, _ in list(self.active.values()):
                try:
                    # poll() also reaps an exited group leader on macOS, where
                    # signalling its dead process group can otherwise raise EPERM.
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await asyncio.to_thread(process.wait)
            if self._task is not None:
                try:
                    await self._task
                except Exception as exc:
                    loop_error = exc
                finally:
                    self._task = None
            await asyncio.to_thread(self._reap)
            await asyncio.to_thread(self.recover)
            if loop_error is not None:
                raise loop_error
        finally:
            if self._lock:
                fcntl.flock(self._lock, fcntl.LOCK_UN)
                self._lock.close()
                self._lock = None


def worker(path, task_id, tool_timeout):
    from agent_core.workflow import WorkflowRuntime

    jobs = JobStore(path)
    with jobs.store.db.connection() as db:
        row = db.execute(
            "SELECT context FROM workflow_jobs WHERE task_id=?", (task_id,)
        ).fetchone()
    if row is None:
        return 0
    context = json.loads(row[0])
    runtime = WorkflowRuntime(path, tool_timeout=tool_timeout)
    try:
        asyncio.run(runtime.resume(task_id, context))
    except ActionError as exc:
        if exc.code in {"RESOURCE_BUSY", "STATE_CONFLICT"}:
            return 75
        with jobs.store.lock(task_id):
            state = jobs.store.get(task_id, context)
            state["result"] = {"code": exc.code, "message": "执行被拒绝"}
            runtime._stop(state, "unrecoverable")
    except Exception as exc:
        with jobs.store.lock(task_id):
            state = jobs.store.get(task_id, context)
            state["result"] = {"code": "WORKER_ERROR", "error_type": type(exc).__name__}
            runtime._settle_receipt(state, context)
            runtime._stop(
                state,
                "worker_error",
                "reconciliation_required"
                if state.get("pending", {}) and state["pending"].get("action_id")
                else "failed",
            )
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--worker", action="store_true")
    p.add_argument("--db", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--tool-timeout", type=float, default=5)
    args = p.parse_args()
    if not args.worker:
        p.error("scheduler is owned by the API lifespan")
    return worker(args.db, args.task_id, args.tool_timeout)


if __name__ == "__main__":
    raise SystemExit(main())
