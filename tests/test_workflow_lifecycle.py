import json
import time
import pytest
from agent_core.action_store import ActionError
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget
from tests.test_workflow import CTX, SEED, SequenceModel, call, run, approve


def test_stale_checkpoint_cannot_overwrite_new_state(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("task", CTX, Budget())
    stale = rt.store.get(state["task_id"], CTX)
    state["replies"].append("new")
    rt.store.save(state)
    with pytest.raises(ActionError, match="版本|并发"):
        rt.store.save(stale)
    assert rt.store.get(state["task_id"], CTX)["replies"] == ["new"]


def test_cancel_control_survives_old_checkpoint_save(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("task", CTX, Budget())
    assert hasattr(rt.store, "request_cancel"), "durable cancellation missing"
    rt.store.request_cancel(state["task_id"], CTX)
    rt.store.save(state)
    assert rt.store.get(state["task_id"], CTX)["cancel_requested"] is True
    with pytest.raises(ActionError):
        rt.store.request_cancel(state["task_id"], {**CTX, "operator": "bob"})


def test_expiration_never_overwrites_approved_action(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([call("seed_test_data", SEED)])
    )
    state = run(rt.start("seed", CTX))
    aid = state["pending"]["action_id"]
    assert hasattr(rt.store, "expire_approvals"), "expiration missing"
    assert rt.store.expire_approvals(time.time() + 301) == 1
    assert rt.store.get(state["task_id"], CTX)["status"] == "expired"
    with pytest.raises(ActionError):
        rt.platform.actions.approve(aid, CTX)
    rt.model = SequenceModel([call("seed_test_data", SEED)])
    state = run(rt.start("second", CTX))
    aid = state["pending"]["action_id"]
    rt.platform.actions.approve(aid, CTX)
    assert rt.store.expire_approvals(time.time() + 301) == 0
    assert rt.platform.actions.get(aid, CTX)["status"] == "approved"


def test_gc_preserves_active_refs_and_receipts(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    active = rt.store.create("active", CTX, Budget())
    done = rt.store.create("done", CTX, Budget())
    payload = {"data": {"rows": [{"text": "x" * 2000}]}}
    a = rt.store.externalize(active["task_id"], payload)["data"]["ref_id"]
    b = rt.store.externalize(done["task_id"], payload)["data"]["ref_id"]
    done["status"] = "completed"
    rt.store.save(done)
    assert hasattr(rt.store, "gc_refs"), "reference retention missing"
    now = time.time() + 8 * 86400
    assert rt.store.gc_refs(now)["count"] == 1
    assert rt.store.read_ref(done["task_id"], {"ref_id": b}, CTX)["success"]
    assert rt.store.gc_refs(now, dry_run=False)["count"] == 1
    assert rt.store.read_ref(active["task_id"], {"ref_id": a}, CTX)["success"]
    with pytest.raises(ActionError):
        rt.store.read_ref(done["task_id"], {"ref_id": b}, CTX)


def test_reset_cannot_race_running_task(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("task", CTX, Budget())
    with rt.store.lock(state["task_id"]):
        with pytest.raises(ActionError):
            rt.platform.reset()
    assert rt.store.get(state["task_id"], CTX)


def test_actual_v0_database_migrates_with_backup(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    rt = WorkflowRuntime(tmp_path / "source.db", model=SequenceModel([]))
    state = rt.store.create("old", CTX, Budget())
    for key in ("schema_version", "mode", "revision"):
        state.pop(key, None)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE workflow_tasks (task_id TEXT PRIMARY KEY,scope TEXT,request_id TEXT,input TEXT,payload TEXT)"
        )
        db.execute(
            "CREATE TABLE workflow_refs (ref_id TEXT PRIMARY KEY,task_id TEXT,payload TEXT)"
        )
        from agent_core.action_store import canonical, scope

        db.execute(
            "INSERT INTO workflow_tasks VALUES (?,?,?,?,?)",
            (state["task_id"], canonical(scope(CTX)), None, "old", json.dumps(state)),
        )
    migrated = WorkflowRuntime(
        path,
        model=SequenceModel(
            [call("query_data", {"table": "gifts"}), {"final": "done"}]
        ),
    )
    result = run(migrated.resume(state["task_id"], CTX))
    assert result["status"] == "completed" and result["revision"] > 0
    assert (tmp_path / "old.db.before-v1.sqlite").exists()


def test_reset_preview_does_not_remove_state(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("active", CTX, Budget())
    preview = rt.platform.reset(dry_run=True)
    assert preview["tables"]["workflow_tasks"] == 1
    assert rt.store.get(state["task_id"], CTX)["status"] == "ready"
