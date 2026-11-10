import pytest
from agent_core.workflow_completion import finish_task
from agent_core.workflow_memory import SessionMemory
from agent_core.workflow_context import build_context
from agent_core.workflow import WorkflowRuntime
from tests.test_agent_decisions import AgentModel, understand, goal
from tests.test_agent_completion import finish
from tests.test_agent_memory import completed_read
from tests.test_workflow import CTX, SEED, call, run


def test_newer_contradictory_read_invalidates_completion(tmp_path):
    rt, s = completed_read(tmp_path / "db")
    g = goal("update_config", {"key": "gift_multiplier", "value": 2}, "ensure_config")
    s.update(
        agent_protocol=2,
        understanding={"user_revision": 0, "goals": [g]},
        steps=[
            {
                "seq": i,
                "tool": "query_config",
                "args": {"key": "gift_multiplier"},
                "result": {
                    "success": True,
                    "data": {"key": "gift_multiplier", "value": v},
                },
            }
            for i, v in enumerate([2, 1])
        ],
    )
    with pytest.raises(ValueError):
        finish_task(s, finish([0], "not_needed")["args"], {})


def test_approval_and_checkpoint_are_atomic_on_sdk_failure(tmp_path, monkeypatch):
    rt = WorkflowRuntime(
        tmp_path / "db", model=AgentModel([understand(), call("seed_test_data", SEED)])
    )
    s = run(rt.start("发10个礼物", CTX))
    aid = s["pending"]["action_id"]
    original = rt.store.save

    def crash(state, *args, **kw):
        if state.get("pending", {}).get("phase") == "execute":
            raise RuntimeError("crash before checkpoint")
        return original(state, *args, **kw)

    monkeypatch.setattr(rt.store, "save", crash)
    with pytest.raises(RuntimeError):
        run(rt.resume(s["task_id"], CTX, action_id=aid, decision="approve"))
    with rt.store.db.connection() as db:
        assert (
            db.execute(
                "SELECT status FROM actions WHERE action_id=?", (aid,)
            ).fetchone()[0]
            == "pending"
        )
    assert not rt.platform.snapshot("gifts")


def test_all_committed_writes_survive_context_and_memory(tmp_path):
    import json

    rt, s = completed_read(tmp_path / "db")
    s.update(
        agent_protocol=2,
        session_memory=[],
        understanding={"user_revision": 0, "goals": []},
    )
    s["steps"] = [
        {
            "seq": i,
            "user_revision": 0,
            "tool": "query_config",
            "args": {"key": "gift_multiplier"},
            "result": {"success": True, "data": {"key": "gift_multiplier", "value": 1}},
        }
        for i in range(30)
    ]
    for i in range(2):
        s["steps"][i].update(
            tool="seed_test_data",
            args=SEED,
            result={
                "success": True,
                "data": {"actual": 10, "batch_id": f"important-{i}"},
            },
        )
    text = json.dumps(build_context(s, [])["messages"])
    assert "important-0" in text and "important-1" in text
    rt.store.save(s)
    memory = json.dumps(SessionMemory(rt.store.db).recent(s["scope"], "new"))
    assert "important-0" in memory and "important-1" in memory


def test_reset_clears_memory_with_tasks(tmp_path):
    rt, s = completed_read(tmp_path / "db")
    assert SessionMemory(rt.store.db).recent(s["scope"], "new")
    rt.platform.reset()
    assert SessionMemory(rt.store.db).recent(s["scope"], "new") == []
