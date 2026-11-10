import time
from contextlib import contextmanager
from agent_core.workflow_runner import WorkflowRunner
from agent_core.workflow_store import Budget
from tests.test_workflow import CTX, run, SequenceModel, call, SEED


def test_orphan_scan_is_bounded_and_revisits_contended_old_tasks(tmp_path, monkeypatch):
    runner = WorkflowRunner(tmp_path / "db", capacity=1)
    states = [runner.jobs.store.create("query", CTX, Budget()) for _ in range(103)]
    states.sort(key=lambda s: s["task_id"])
    old = states[0]
    old["created_at"] = 1
    runner.jobs.store.save(old)
    with runner.jobs.store.lock(old["task_id"]):
        runner.recover()
    assert old["task_id"] in runner._retry_after
    assert runner._orphan_cursor == states[99]["task_id"]
    # Cursor advances even when the bounded queue is full.
    runner.recover()
    assert runner._orphan_cursor == states[-1]["task_id"]
    with runner.jobs.store.db.connection(write=True) as db:
        db.execute("UPDATE workflow_jobs SET status='done'")
    runner.recover()  # wrap
    monkeypatch.setattr(
        "agent_core.workflow_runner.time.monotonic", lambda: time.time() + 100
    )
    runner.recover()
    with runner.jobs.store.db.connection() as db:
        assert (
            db.execute(
                "SELECT status FROM workflow_jobs WHERE task_id=?", (old["task_id"],)
            ).fetchone()[0]
            == "queued"
        )


def test_terminal_history_does_not_decode_payloads_or_take_locks(tmp_path, monkeypatch):
    runner = WorkflowRunner(tmp_path / "db")
    for _ in range(10):
        state = runner.jobs.store.create("query", CTX, Budget())
        state["status"] = "completed"
        runner.jobs.store.save(state)

    def unexpected(*args, **kwargs):
        raise AssertionError("terminal history was inspected")

    monkeypatch.setattr(runner.jobs.store, "lock", unexpected)
    monkeypatch.setattr("agent_core.workflow_runner.json.loads", unexpected)
    runner.recover()
    assert runner.jobs.store.expire_approvals(time.time()) == 0


def test_unexpired_approval_is_not_locked_by_maintenance(tmp_path, monkeypatch):
    from agent_core.workflow import WorkflowRuntime

    runtime = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([call("seed_test_data", SEED)])
    )
    run(runtime.start("seed", CTX))

    def unexpected(*args, **kwargs):
        raise AssertionError("unexpired approval locked")

    monkeypatch.setattr(runtime.store, "lock", unexpected)
    assert runtime.store.expire_approvals(time.time()) == 0
