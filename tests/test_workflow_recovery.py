import asyncio
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest
from agent_core.action_store import ActionError
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget
from agent_core.mock_platforms import MockPlatforms
from tests.test_workflow import CTX, SEED, SequenceModel, call, run, approve


def test_parallel_tasks_do_not_supersede_each_other(tmp_path):
    path = tmp_path / "db"
    a = WorkflowRuntime(
        path, model=SequenceModel([call("seed_test_data", SEED), {"final": "done"}])
    )
    b = WorkflowRuntime(
        path, model=SequenceModel([call("seed_test_data", SEED), {"final": "done"}])
    )
    sa = run(a.start("a", CTX))
    sb = run(b.start("b", CTX))
    assert approve(a, sa)["status"] == "completed"
    assert approve(b, sb)["status"] == "completed"
    assert len(a.platform.snapshot("gifts")) == 2


@pytest.mark.parametrize("boundary", ["before_receipt", "after_receipt"])
def test_process_crash_resumes_exactly_once(tmp_path, boundary):
    path = tmp_path / "db"
    rt = WorkflowRuntime(path, model=SequenceModel([call("seed_test_data", SEED)]))
    state = run(rt.start("发放后查询", CTX))
    program = """
import asyncio,os,sys,json
from contextlib import contextmanager
from agent_core.workflow import WorkflowRuntime
from tests.test_workflow import SequenceModel,CTX
rt=WorkflowRuntime(sys.argv[1],model=SequenceModel([]),isolate_tools=False)
if sys.argv[4]=='after_receipt':
    rt.platform.actions.complete=lambda *a: os._exit(86)
else:
    original=rt.platform.actions.connection
    @contextmanager
    def connection(*args,**kwargs):
        with original(*args,**kwargs) as db:
            db.set_trace_callback(lambda sql: os._exit(86) if sql.startswith('INSERT INTO platform_receipts') else None)
            yield db
    rt.platform.actions.connection=connection
asyncio.run(rt.resume(sys.argv[2],CTX,action_id=sys.argv[3],decision='approve'))
"""
    p = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(path),
            state["task_id"],
            state["pending"]["action_id"],
            boundary,
        ],
        capture_output=True,
        timeout=20,
    )
    assert p.returncode == 86, p.stderr.decode()
    restarted = WorkflowRuntime(
        path,
        model=SequenceModel(
            [call("query_data", {"table": "gifts"}), {"final": "done"}]
        ),
        retry_delays=(0, 0),
    )
    result = run(restarted.resume(state["task_id"], CTX))
    assert result["status"] == "completed"
    assert result["steps"][1]["result"]["data"]["total_quantity"] == 10
    assert len(restarted.platform.snapshot("gifts")) == 1
    with restarted.store.db.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM workflow_audit WHERE event='approve'"
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT count(*) FROM workflow_audit WHERE event='receipt'"
            ).fetchone()[0]
            == 1
        )


def test_scoped_refs_pagination_and_compact_context(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("query", CTX, Budget())
    rows = [{"id": i, "text": "x" * 100} for i in range(100)]
    compact = rt.store.externalize(
        state["task_id"],
        {"success": True, "status": "success", "code": "OK", "data": {"rows": rows}},
    )
    rid = compact["data"]["ref_id"]
    assert len(compact["data"]["sample_3"]) == 3
    assert (
        rt.store.read_ref(
            state["task_id"], {"ref_id": rid, "offset": 90, "limit": 3}, CTX
        )["data"]["rows"]
        == rows[90:93]
    )
    other = rt.store.create("other", CTX, Budget())
    with pytest.raises(ActionError):
        rt.store.read_ref(other["task_id"], {"ref_id": rid}, CTX)
    with pytest.raises(ActionError):
        rt.store.read_ref(state["task_id"], {"ref_id": rid}, {**CTX, "env": "prod"})


def test_locked_task_rejects_concurrent_resume(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("q", CTX, Budget())
    with rt.store.lock(state["task_id"]):
        with ThreadPoolExecutor(max_workers=1) as pool:
            f = pool.submit(run, rt.resume(state["task_id"], CTX))
            with pytest.raises(ActionError, match="另一执行者"):
                f.result()


def test_reset_invalidates_workflows_and_refs(tmp_path):
    path = tmp_path / "db"
    rt = WorkflowRuntime(path, model=SequenceModel([call("seed_test_data", SEED)]))
    state = run(rt.start("发礼物", CTX))
    MockPlatforms(path).reset()
    with pytest.raises(ActionError, match="不存在"):
        run(rt.resume(state["task_id"], CTX))


def test_budget_and_approval_survive_restart(tmp_path):
    path = tmp_path / "db"
    rt = WorkflowRuntime(path, model=SequenceModel([call("seed_test_data", SEED)]))
    state = run(rt.start("发礼物", CTX, Budget(max_steps=1)))
    restarted = WorkflowRuntime(path, model=SequenceModel([{"final": "done"}]))
    assert approve(restarted, state)["stop_reason"] == "max_steps"
    assert len(restarted.platform.snapshot("gifts")) == 1


@pytest.mark.parametrize("exhausted", [False, True])
def test_restart_reconciles_committed_receipt_before_time_budget(tmp_path, exhausted):
    import time

    rt = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([call("seed_test_data", SEED)])
    )
    state = run(rt.start("seed", CTX))
    aid = state["pending"]["action_id"]
    rt.platform.actions.approve(aid, CTX)
    rt.platform.actions.running(aid, CTX)
    assert rt.platform.execute("seed_test_data", SEED, {**CTX, "action_id": aid})[
        "success"
    ]
    state.update(
        status="running", active_since=time.time() - (130 if exhausted else 0.01)
    )
    state["pending"]["phase"] = "execute"
    rt.store.save(state)
    restarted = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([{"final": "done"}])
    )
    result = run(restarted.resume(state["task_id"], CTX))
    assert result["stop_reason"] == ("timeout" if exhausted else "finished")
    assert result["pending"] is None
    assert result["steps"][0]["result"]["data"]["actual"] == 10
    assert restarted.platform.actions.get(aid, CTX)["status"] == "success"
    with rt.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM platform_receipts").fetchone()[0] == 1
        assert (
            db.execute(
                "SELECT count(*) FROM workflow_audit WHERE event='reconcile'"
            ).fetchone()[0]
            == 1
        )


def test_default_offline_chain_and_http_restart(tmp_path, monkeypatch):
    import httpx
    from api.offline_server import create_app

    monkeypatch.setenv("LLM_MODE", "offline")
    path = tmp_path / "db"

    async def scenario():
        rt = WorkflowRuntime(path)
        app = create_app(workflow=rt)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/workflows",
                json={"user_input": "给用户123发10个礼物301到背包，然后查询核验", "context": CTX},
            )
            assert r.status_code == 200, r.text
            state = r.json()
        await app.state.runner.stop()
        app = create_app(workflow=WorkflowRuntime(path))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/workflows/" + state["task_id"] + "/resume",
                json={
                    "context": CTX,
                    "action_id": state["pending"]["action_id"],
                    "decision": "approve",
                },
            )
            assert r.json()["status"] == "completed", r.text
            assert r.json()["steps"][1]["result"]["data"]["total_quantity"] == 10
        await app.state.runner.stop()

    run(scenario())


def test_unknown_environment_rejected_before_model_call(tmp_path):
    model = SequenceModel([])
    rt = WorkflowRuntime(tmp_path / "db", model=model)
    with pytest.raises(ActionError, match="环境"):
        run(rt.start("发礼物", {**CTX, "env": "prod "}))
    assert model.calls == 0


def test_expired_approval_can_be_replanned_without_mutating_old_snapshot(tmp_path):
    import sqlite3

    path = tmp_path / "db"
    rt = WorkflowRuntime(path, model=SequenceModel([call("seed_test_data", SEED)]))
    state = run(rt.start("发礼物", CTX))
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE actions SET expires_at=0 WHERE action_id=?",
            (state["pending"]["action_id"],),
        )
    with pytest.raises(ActionError, match="过期"):
        approve(rt, state)
    assert not rt.platform.snapshot("gifts")


def test_retry_pause_after_transient_preserves_attempt_limit(tmp_path):
    path = tmp_path / "db"
    rt = WorkflowRuntime(
        path, model=SequenceModel([call("seed_test_data", SEED)]), retry_delays=(0, 0)
    )
    state = run(rt.start("发礼物", {**CTX, "fault_id": "f_5xx"}))
    result = approve(rt, state)
    restarted = WorkflowRuntime(path, model=SequenceModel([]))
    replay = run(restarted.resume(result["task_id"], CTX))
    assert replay["tool_calls"] == 3 and replay["stop_reason"] == "unrecoverable"


def test_crash_after_preparing_approval_recovers_without_another_model_call(tmp_path):
    import sqlite3

    path = tmp_path / "db"
    rt = WorkflowRuntime(path, model=SequenceModel([]))
    state = rt.store.create("发礼物", CTX, Budget(max_steps=1))
    program = """
import os,asyncio,sys
from agent_core.workflow import WorkflowRuntime
from tests.test_workflow import CTX,SEED,SequenceModel,call
rt=WorkflowRuntime(sys.argv[1],model=SequenceModel([call('seed_test_data',SEED)]))
original=rt.platform.prepare
def crash(*args,**kwargs):
    original(*args,**kwargs)
    os._exit(86)
rt.platform.prepare=crash
asyncio.run(rt.resume(sys.argv[2],CTX))
"""
    child = subprocess.run(
        [sys.executable, "-c", program, str(path), state["task_id"]],
        capture_output=True,
        timeout=20,
    )
    assert child.returncode == 86, child.stderr.decode()
    recovered = run(rt.resume(state["task_id"], CTX))
    assert recovered["status"] == "approval_wait"
    assert rt.model.calls == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 1
    result = approve(rt, recovered)
    assert result["stop_reason"] == "max_steps"
    assert len(rt.platform.snapshot("gifts")) == 1
