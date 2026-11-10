from agent_core.workflow import WorkflowRuntime
from tests.test_workflow import CTX, SEED, SequenceModel, call, run, approve


def test_read_cannot_substantiate_write_completion(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [call("query_data", {"table": "gifts"}), {"final": "已发放10个礼物"}]
        ),
    )
    state = run(rt.start("给用户123发10个礼物301到背包", CTX))
    assert state["stop_reason"] == "no_evidence"
    assert state["result"]["effects"] == []
    assert "已发放10个礼物" not in state["result"]["message"]
    assert state["result"]["unfulfilled"] == ["seed_test_data"]
    assert not rt.platform.snapshot("gifts")


def test_final_summary_uses_receipt_quantity_and_exact_batch_verification(tmp_path):
    class Model(SequenceModel):
        async def next(self, messages, context, max_tokens):
            if self.calls == 1:
                batch = next(row["batch_id"] for row in rt.platform.snapshot("gifts"))
                self.calls += 1
                return call("query_data", {"table": "gifts", "batch_id": batch})
            return await super().next(messages, context, max_tokens)

    rt = WorkflowRuntime(
        tmp_path / "db",
        model=Model([call("seed_test_data", SEED), {"final": "已发放999个礼物"}]),
    )
    state = approve(rt, run(rt.start("发放后查询核验", CTX)))
    assert state["status"] == "completed"
    assert state["result"]["effects"][0]["actual"] == 10
    assert state["result"]["verification"][0]["verified"] is True
    assert "999" not in state["result"]["message"]


def test_unrelated_read_is_not_write_verification(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [
                call("seed_test_data", SEED),
                call("query_data", {"table": "gifts", "user_id": 456}),
                {"final": "核验成功"},
            ]
        ),
    )
    state = approve(rt, run(rt.start("发放礼物后核验", CTX)))
    assert state["stop_reason"] == "no_evidence"
    assert state["result"]["effects"][0]["actual"] == 10
    assert state["result"]["verification"][0]["verified"] is False


def test_unknown_goal_reports_only_observed_facts(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [call("query_data", {"table": "gifts"}), {"final": "发放成功，权限已升级"}]
        ),
    )
    state = run(rt.start("inspect", CTX))
    assert state["status"] == "completed"
    assert state["result"]["completion_scope"] == "observed_operations"
    assert state["result"]["effects"] == []
    assert "发放成功" not in state["result"]["message"]


def test_missing_quantity_can_resume_after_restart_with_bound_approval(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [call("seed_test_data", {"table": "gifts", "user_id": 123, "gift_id": 301})]
        ),
    )
    state = run(rt.start("给用户123发礼物301到背包", CTX))
    assert state["status"] == "clarification_wait"
    assert state["result"]["missing_fields"] == ["quantity"]
    assert not rt.platform.actions.list_actions()
    restarted = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([{"final": "done"}])
    )
    state = run(restarted.resume(state["task_id"], CTX, reply="10个"))
    assert state["status"] == "approval_wait"
    assert state["pending"]["args"]["quantity"] == 10
    assert not restarted.platform.snapshot("gifts")
    state = approve(restarted, state)
    assert state["status"] == "completed"
    assert restarted.platform.snapshot("gifts")[0]["quantity"] == 10


def test_clarification_cannot_change_already_supplied_write_fields(tmp_path):
    import pytest
    from agent_core.action_store import ActionError

    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [call("seed_test_data", {"table": "gifts", "user_id": 123, "gift_id": 301})]
        ),
    )
    state = run(rt.start("发放礼物", CTX))
    assert state["status"] == "clarification_wait"
    with pytest.raises(ActionError):
        run(rt.resume(state["task_id"], CTX, reply='{"quantity":10,"user_id":456}'))
    assert not rt.platform.actions.list_actions()


def test_invalid_clarification_value_keeps_waiting_without_write(tmp_path):
    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [call("seed_test_data", {"table": "gifts", "user_id": 123, "gift_id": 301})]
        ),
    )
    state = run(rt.start("发放礼物", CTX))
    assert state["status"] == "clarification_wait"
    result = run(rt.resume(state["task_id"], CTX, reply="-1"))
    assert result["status"] == "clarification_wait"
    assert result["result"]["code"] == "BAD_ARGS"
    assert not rt.platform.actions.list_actions()


def test_missing_write_identity_is_bad_args_not_unrecoverable(tmp_path):
    for i, context in enumerate(({}, {"operator": "alice"}, {"env": "uat"})):
        rt = WorkflowRuntime(
            tmp_path / str(i), model=SequenceModel([call("seed_test_data", SEED)])
        )
        state = run(rt.start("发礼物", context))
        assert state["stop_reason"] == "bad_args"
        assert state["result"]["code"] == "BAD_ARGS"
        assert not rt.platform.actions.list_actions()


def test_job_resume_clarification_prepares_approval_without_execution(tmp_path):
    from agent_core.workflow_jobs import JobStore

    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [call("seed_test_data", {"table": "gifts", "user_id": 123, "gift_id": 301})]
        ),
    )
    state = run(rt.start("发放礼物", CTX))
    jobs = JobStore(tmp_path / "db")
    waiting = jobs.resume(state["task_id"], CTX, reply="-1")
    assert waiting["status"] == "clarification_wait"
    with jobs.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_jobs").fetchone()[0] == 0
    queued = jobs.resume(state["task_id"], CTX, reply="10")
    assert queued["pending"]["phase"] == "prepare"
    state = run(rt.resume(state["task_id"], CTX))
    assert state["status"] == "approval_wait"
    assert state["pending"]["args"] == SEED
    assert not rt.platform.snapshot("gifts")


def test_busy_approval_api_has_retry_hint_and_no_side_effect(tmp_path):
    import httpx
    from api.offline_server import create_app
    from agent_core.workflow_runner import WorkflowRunner

    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel([call("seed_test_data", SEED), {"final": "done"}]),
    )
    state = run(rt.start("seed", CTX))
    runner = WorkflowRunner(tmp_path / "db")

    async def no_start():
        pass

    runner.start = no_start
    app = create_app(workflow=rt, runner=runner)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            payload = {
                "context": CTX,
                "action_id": state["pending"]["action_id"],
                "decision": "approve",
                "dispatch": "queued",
            }
            with rt.store.lock(state["task_id"]):
                response = await client.post(
                    f"/workflows/{state['task_id']}/resume", json=payload
                )
            assert response.status_code == 409
            assert response.headers["Retry-After"] == "1"
            assert (
                rt.platform.actions.get(payload["action_id"], CTX)["status"]
                == "pending"
            )
            assert not rt.platform.snapshot("gifts")
            response = await client.post(
                f"/workflows/{state['task_id']}/resume", json=payload
            )
            assert response.status_code == 202

    run(scenario())
    result = run(rt.resume(state["task_id"], CTX))
    assert result["status"] == "completed"
    assert sum(r["quantity"] for r in rt.platform.snapshot("gifts")) == 10


def test_cleanup_verification_requires_gift_table_not_empty_script_history():
    from agent_core.workflow_outcome import verified_effect

    effect = {
        "seq": 0,
        "tool": "cleanup_data",
        "data": {"batch_id": "batch", "actual": 10},
    }
    wrong = {
        "seq": 1,
        "tool": "query_data",
        "args": {"table": "script_runs", "batch_id": "batch"},
        "result": {"success": True, "data": {"total_quantity": 0, "rows": []}},
    }
    assert not verified_effect(effect, [wrong])
