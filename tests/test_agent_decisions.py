import json
import pytest
from agent_core.action_store import ActionError
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_jobs import JobStore
from tests.test_workflow import CTX, SEED, SequenceModel, call, run


class AgentModel(SequenceModel):
    agent_protocol = 2


def goal(tool="seed_test_data", args=None, kind="write", source="u0", **extra):
    return {
        "id": "g1",
        "kind": kind,
        "tool": tool,
        "args": args if args is not None else SEED,
        "source_ids": [source],
        **extra,
    }


def understand(goals=None, revision=0):
    return call("update_task", {"user_revision": revision, "goals": goals or [goal()]})


def test_model_reinterprets_missing_fields_and_corrections(tmp_path):
    model = AgentModel(
        [
            call("ask_clarification", {"question": "请提供用户和数量"}),
            understand([goal(args={**SEED, "user_id": 456}, source="u1")], 1),
            call("seed_test_data", {**SEED, "user_id": 456}),
        ]
    )
    rt = WorkflowRuntime(tmp_path / "db", model=model)
    state = run(rt.start("给用户123发礼物301，数量稍后补充", CTX))
    state = run(rt.resume(state["task_id"], CTX, reply="10个，用户改成456"))
    assert state["status"] == "approval_wait"
    assert state["pending"]["args"] == {**SEED, "user_id": 456}
    assert state["agent_protocol"] == 2
    assert not rt.platform.snapshot("gifts")


@pytest.mark.parametrize("queued", [False, True])
def test_correction_revokes_approval_before_replanning(tmp_path, queued):
    model = AgentModel(
        [
            understand(),
            call("seed_test_data", SEED),
            understand([goal(args={**SEED, "quantity": 3}, source="u1")], 1),
            call("seed_test_data", {**SEED, "quantity": 3}),
        ]
    )
    rt = WorkflowRuntime(tmp_path / "db", model=model)
    state = run(rt.start("给用户123发10个礼物301", CTX))
    old = state["pending"]["action_id"]
    if queued:
        jobs = JobStore(tmp_path / "db")
        state = jobs.resume(state["task_id"], CTX, reply="改成3个")
        state = run(rt.resume(state["task_id"], CTX))
    else:
        state = run(rt.resume(state["task_id"], CTX, reply="改成3个"))
    assert state["status"] == "approval_wait"
    assert state["pending"]["action_id"] != old
    assert state["pending"]["args"]["quantity"] == 3
    with rt.store.db.connection() as db:
        assert (
            db.execute(
                "SELECT status FROM actions WHERE action_id=?", (old,)
            ).fetchone()[0]
            == "cancelled"
        )
    with pytest.raises(ActionError):
        run(rt.resume(state["task_id"], CTX, action_id=old, decision="approve"))
    assert not rt.platform.snapshot("gifts")


def test_reply_and_approval_are_mutually_exclusive(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db", model=AgentModel([understand(), call("seed_test_data", SEED)])
    )
    s = run(rt.start("发礼物", CTX))
    with pytest.raises((ActionError, ValueError)):
        run(
            rt.resume(
                s["task_id"],
                CTX,
                action_id=s["pending"]["action_id"],
                decision="approve",
                reply="改成3个",
            )
        )
    assert not rt.platform.snapshot("gifts")


def test_model_cannot_execute_without_sourced_current_goal(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db",
        model=AgentModel([call("seed_test_data", SEED), call("seed_test_data", SEED)]),
    )
    state = run(rt.start("发礼物", CTX))
    assert state["status"] == "failed"
    assert not rt.platform.actions.list_actions()


def test_forged_source_and_stale_revision_rejected(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db",
        model=AgentModel([understand([goal(source="u999")]), understand(revision=7)]),
    )
    state = run(rt.start("发礼物", CTX))
    assert state["stop_reason"] == "bad_args"
    assert not rt.platform.actions.list_actions()


def test_verification_link_is_an_explicit_goal_id_with_helpful_schema():
    from agent_core.workflow_decisions import decision_catalog, update_task

    schema = next(
        t["function"]["parameters"]
        for t in decision_catalog()
        if t["function"]["name"] == "update_task"
    )
    assert "write_goal_id" in schema["$defs"]["Goal"]["properties"]
    assert "description" in schema["$defs"]["Goal"]["properties"]["write_goal_id"]
    state = {"input": "发礼物并核验", "replies": []}
    with pytest.raises(ValueError):
        update_task(
            state,
            {
                "user_revision": 0,
                "goals": [
                    goal(),
                    {
                        "id": "v1",
                        "kind": "verify",
                        "source_ids": ["u0"],
                        "write_goal_id": "数量应当相同",
                    },
                ],
            },
        )
    result = update_task(
        state,
        {
            "user_revision": 0,
            "goals": [
                goal(),
                {
                    "id": "v1",
                    "kind": "verify",
                    "source_ids": ["u0"],
                    "write_goal_id": "g1",
                },
            ],
        },
    )
    assert result["success"]
