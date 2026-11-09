import json
import pytest
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget
from tests.test_workflow import CTX, SEED, SequenceModel, call, run


def test_runtime_reference_page_never_reexternalizes(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("read", CTX, Budget())
    rows = [{"id": i, "text": "中文" * 20} for i in range(100)]
    ref = rt.store.externalize(
        state["task_id"],
        {"success": True, "status": "success", "code": "OK", "data": {"rows": rows}},
    )
    rt.model = SequenceModel(
        [
            call("read_ref", {"ref_id": ref["data"]["ref_id"], "limit": 100}),
            {"final": "done"},
        ]
    )
    state = run(rt.resume(state["task_id"], CTX))
    assert state["steps"][0]["result"]["data"].get("rows") == rows
    with rt.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_refs").fetchone()[0] == 1


def test_reference_byte_pages_and_oversized_row(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("read", CTX, Budget())
    rows = [{"id": i, "text": "中" * 1000} for i in range(15)]
    ref = rt.store.externalize(state["task_id"], {"data": {"rows": rows}})["data"][
        "ref_id"
    ]
    offset = 0
    found = []
    while True:
        result = rt.store.read_ref(
            state["task_id"], {"ref_id": ref, "offset": offset, "limit": 100}, CTX
        )
        assert (
            len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
            <= 16384
        )
        found.extend(result["data"]["rows"])
        offset = result["data"]["next_offset"]
        if offset is None:
            break
    assert found == rows
    ref = rt.store.externalize(
        state["task_id"], {"data": {"rows": [{"text": "x" * 20000}]}}
    )["data"]["ref_id"]
    assert (
        rt.store.read_ref(state["task_id"], {"ref_id": ref}, CTX)["code"]
        == "ROW_TOO_LARGE"
    )


def test_dry_run_is_terminal_and_cannot_be_upgraded(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([call("seed_test_data", SEED)])
    )
    state = run(rt.start("preview", {**CTX, "dry_run": True}))
    assert state["status"] == "planned"
    assert state["mode"] == "dry_run"
    assert rt.platform.actions.list_actions() == []
    state = run(
        rt.resume(state["task_id"], CTX, decision="approve", action_id="anything")
    )
    assert state["status"] == "planned"
    assert rt.platform.snapshot("gifts") == []


def test_checkpoint_migration_and_future_version_rejected(tmp_path):
    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("v0", CTX, Budget())
    state.pop("schema_version", None)
    state.pop("mode", None)
    rt.store.save(state)
    loaded = rt.store.get(state["task_id"], CTX)
    assert loaded["schema_version"] == 1 and loaded["mode"] == "execute"
    state["schema_version"] = 999
    rt.store.save(state)
    with pytest.raises(ValueError, match="版本"):
        rt.store.get(state["task_id"], CTX)
