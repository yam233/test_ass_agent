import importlib.util
import pytest
from agent_core.action_store import ActionError
from agent_core.workflow_store import Budget
from tests.test_workflow import CTX, SEED, SequenceModel, call, run


def queue(path, capacity=100):
    assert importlib.util.find_spec(
        "agent_core.workflow_jobs"
    ), "persistent job store missing"
    from agent_core.workflow_jobs import JobStore

    return JobStore(path, capacity=capacity)


def test_queue_full_rolls_back_task_and_replay_is_idempotent(tmp_path):
    jobs = queue(tmp_path / "db", capacity=1)
    first = jobs.submit("查询礼物", {**CTX, "request_id": "one"}, Budget())
    replay = jobs.submit("查询礼物", {**CTX, "request_id": "one"}, Budget())
    assert replay["task_id"] == first["task_id"]
    with pytest.raises(ActionError, match="队列"):
        jobs.submit("second", CTX, Budget())
    with jobs.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_tasks").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM workflow_jobs").fetchone()[0] == 1


def test_approve_and_enqueue_share_one_transaction(tmp_path):
    from agent_core.workflow import WorkflowRuntime

    rt = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([call("seed_test_data", SEED)])
    )
    state = run(rt.start("seed", CTX))
    aid = state["pending"]["action_id"]
    jobs = queue(tmp_path / "db", capacity=1)
    jobs.submit("queue full", CTX, Budget())
    with pytest.raises(ActionError):
        jobs.resume(state["task_id"], CTX, action_id=aid, decision="approve")
    assert rt.platform.actions.get(aid, CTX)["status"] == "pending"
    assert rt.store.get(state["task_id"], CTX)["status"] == "approval_wait"


def test_queued_cancel_is_durable_and_scope_checked(tmp_path):
    jobs = queue(tmp_path / "db")
    state = jobs.submit("read", CTX, Budget())
    with pytest.raises(ActionError):
        jobs.cancel(state["task_id"], {**CTX, "operator": "bob"})
    result = jobs.cancel(state["task_id"], CTX)
    assert result["status"] == "cancelled"
    assert jobs.store.get(state["task_id"], CTX)["cancel_requested"]
