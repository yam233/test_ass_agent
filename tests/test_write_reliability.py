import sys
import asyncio
import json
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from agent_core.mock_platforms import MockPlatforms
from scripts.evaluate_backpack import CASES_PATH, offline_agent, run_case

CTX = {"operator": "alice", "session_id": "s1", "env": "uat"}
PARAMS = {"user_id": 123, "gift_id": 301, "quantity": 10}
TOOL = "add_gift_to_backpack"
TEXT = "给用户123发10个礼物301到背包"


def invoke(agent, text, **context):
    return asyncio.run(agent.ainvoke(text, {**CTX, **context}))


def pending(agent):
    result = invoke(agent, TEXT)
    assert result["code"] == "CONFIRM_REQUIRED"
    return result["data"]["action_id"]


def quantity(path):
    return sum(row["quantity"] for row in MockPlatforms(path).snapshot("gifts"))


@pytest.mark.parametrize(
    "case", json.loads(CASES_PATH.read_text()), ids=lambda c: c["id"]
)
def test_fixed_backpack_regression(case, tmp_path):
    result = asyncio.run(run_case(case, tmp_path / "state.sqlite"))
    assert result["passed"], result


def test_boolean_flags_do_not_bypass_bound_approval(tmp_path):
    agent = offline_agent(tmp_path / "state.sqlite")
    result = invoke(agent, TEXT, approved=True, execute_confirmed=True)
    assert result["code"] == "CONFIRM_REQUIRED"
    assert quantity(tmp_path / "state.sqlite") == 0
    direct = agent.mock_platforms.execute(
        TOOL, PARAMS, {**CTX, "execute_confirmed": True}
    )
    assert not direct["success"]


@pytest.mark.parametrize(
    "changed",
    [{"operator": "bob"}, {"session_id": "s2"}, {"env": "staging"}, {"env": "prod"}],
)
def test_approval_rejects_scope_changes(tmp_path, changed):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    action_id = pending(agent)
    result = invoke(agent, "确认执行", action_id=action_id, **changed)
    assert not result["success"]
    assert quantity(path) == 0


def test_changed_arguments_and_tool_cannot_use_approved_action(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    action_id = pending(agent)
    agent.mock_platforms.actions.approve(action_id, CTX)
    for tool, params in [
        (TOOL, {**PARAMS, "quantity": 20}),
        ("add_gift_to_exclusive_tab", PARAMS),
    ]:
        result = agent.mock_platforms.execute(
            tool, params, {**CTX, "action_id": action_id}
        )
        assert result["code"] == "APPROVAL_MISMATCH"
    assert quantity(path) == 0


def test_expired_and_superseded_actions_cannot_execute(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    old = pending(agent)
    current = pending(agent)
    assert invoke(agent, "确认执行", action_id=old)["code"] == "APPROVAL_INVALID"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE actions SET expires_at=0 WHERE action_id=?", (current,))
    assert invoke(agent, "确认执行", action_id=current)["code"] == "APPROVAL_EXPIRED"
    assert quantity(path) == 0


def test_request_replay_reuses_action_but_explicit_repeat_is_new(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    first = invoke(agent, TEXT, request_id="request-1")
    replay = invoke(agent, TEXT, request_id="request-1")
    action_id = first["data"]["action_id"]
    assert replay["data"]["action_id"] == action_id
    assert invoke(agent, "确认执行", action_id=action_id)["success"]
    second = invoke(agent, "再发一次")
    assert second["data"]["action_id"] != action_id
    assert invoke(agent, "确认执行", action_id=second["data"]["action_id"])["success"]
    assert quantity(path) == 20


def test_concurrent_retries_across_instances_have_one_side_effect(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    action_id = pending(agent)
    agent.mock_platforms.actions.approve(action_id, CTX)

    def execute(_):
        return MockPlatforms(path).execute(
            TOOL, PARAMS, {**CTX, "action_id": action_id}
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(execute, range(8)))
    assert all(result["success"] for result in results)
    assert quantity(path) == 10
    assert len(MockPlatforms(path).snapshot("gifts")) == 1


def test_process_exits_after_platform_commit_before_action_result(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    action_id = pending(agent)
    # Real child process exits after the platform commit, before ledger completion.
    program = """
import asyncio, os, sys
from scripts.evaluate_backpack import offline_agent
agent=offline_agent(sys.argv[1])
agent.mock_platforms.actions.complete=lambda *a, **k: os._exit(86)
asyncio.run(agent.ainvoke("确认执行", {"operator":"alice","session_id":"s1","env":"uat","action_id":sys.argv[2]}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", program, str(path), action_id],
        timeout=20,
        capture_output=True,
    )
    assert proc.returncode == 86, proc.stderr.decode()
    assert quantity(path) == 10
    restarted = offline_agent(path)
    result = invoke(restarted, "重试执行", action_id=action_id)
    assert result["success"]
    assert result["data"]["reconciled"] is True
    assert quantity(path) == 10
    assert restarted.mock_platforms.actions.get(action_id, CTX)["status"] == "success"


def test_partial_retry_does_not_silently_top_up_or_duplicate(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    action_id = pending(agent)
    first = invoke(agent, "确认执行", action_id=action_id, fault_id="f_halfseed")
    retry = invoke(offline_agent(path), "重试执行", action_id=action_id)
    assert first["status"] == retry["status"] == "partial_success"
    assert retry["data"]["actual"] == 5
    assert quantity(path) == 5


def test_process_exit_before_platform_receipt_rolls_back_write(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    action_id = pending(agent)
    program = """
import asyncio, os, sys
from contextlib import contextmanager
from scripts.evaluate_backpack import offline_agent
agent=offline_agent(sys.argv[1])
original=agent.mock_platforms.actions.connection
@contextmanager
def interrupted_connection(*args, **kwargs):
    with original(*args, **kwargs) as db:
        db.set_trace_callback(lambda sql: os._exit(87) if sql.startswith("INSERT INTO platform_receipts") else None)
        yield db
agent.mock_platforms.actions.connection=interrupted_connection
asyncio.run(agent.ainvoke("确认执行", {"operator":"alice","session_id":"s1","env":"uat","action_id":sys.argv[2]}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", program, str(path), action_id],
        timeout=20,
        capture_output=True,
    )
    assert proc.returncode == 87, proc.stderr.decode()
    assert quantity(path) == 0
    result = invoke(offline_agent(path), "重试执行", action_id=action_id)
    assert result["success"]
    assert quantity(path) == 10


def test_prewrite_transient_retry_and_request_conflict(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    plan = invoke(agent, TEXT, request_id="same-request")
    action_id = plan["data"]["action_id"]
    conflict = invoke(agent, "给用户123发20个礼物301到背包", request_id="same-request")
    assert conflict["code"] == "REQUEST_CONFLICT"
    timed_out = invoke(agent, "确认执行", action_id=action_id, fault_id="f_timeout")
    assert timed_out["code"] == "TIMEOUT"
    assert quantity(path) == 0
    assert invoke(offline_agent(path), "重试执行", action_id=action_id)["success"]
    assert quantity(path) == 10


def test_expiry_does_not_hide_committed_outcome_and_reset_invalidates_actions(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    action_id = pending(agent)
    result = invoke(agent, "确认执行", action_id=action_id, fault_id="f_response_loss")
    assert result["code"] == "OUTCOME_UNKNOWN"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE actions SET expires_at=0 WHERE action_id=?", (action_id,))
    assert invoke(agent, "重试执行", action_id=action_id)["success"]
    assert quantity(path) == 10
    agent.mock_platforms.reset()
    assert invoke(agent, "重试执行", action_id=action_id)["code"] == "ACTION_NOT_FOUND"
    assert quantity(path) == 0


def test_dry_run_cannot_turn_into_an_approved_write(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    preview = invoke(agent, TEXT, dry_run=True)
    assert preview["status"] == "planned"
    assert not preview["data"].get("action_id")
    assert not invoke(agent, "确认执行")["success"]
    assert quantity(path) == 0


def test_delayed_confirmation_without_id_cannot_approve_replacement(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = offline_agent(path)
    pending(agent)
    replacement = invoke(agent, "给用户123发20个礼物301到背包")
    implicit = invoke(agent, "确认执行")
    assert implicit["code"] == "ACTION_ID_REQUIRED"
    assert quantity(path) == 0
    assert invoke(agent, "确认执行", action_id=replacement["data"]["action_id"])["success"]
    assert quantity(path) == 20


def test_http_action_can_be_confirmed_and_retried_after_restart(tmp_path):
    import httpx
    from api.offline_server import create_app

    path = tmp_path / "state.sqlite"

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(offline_agent(path))),
            base_url="http://local.test",
        ) as client:
            response = (
                await client.post(
                    "/agent/execute", json={"user_input": TEXT, "context": CTX}
                )
            ).json()
        action_id = response["data"]["action_id"]
        bound = {**CTX, "action_id": action_id}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(offline_agent(path))),
            base_url="http://local.test",
        ) as client:
            lost = (
                await client.post(
                    "/agent/execute",
                    json={
                        "user_input": "确认执行",
                        "context": {**bound, "fault_id": "f_response_loss"},
                    },
                )
            ).json()
            assert lost["code"] == "OUTCOME_UNKNOWN"
            retried = (
                await client.post(
                    "/agent/langgraph/execute",
                    json={"user_input": "重试执行", "context": bound},
                )
            ).json()
            assert retried["data"]["actual"] == 10
            assert retried["data"]["reconciled"]

    asyncio.run(scenario())
    assert quantity(path) == 10


def test_delayed_failure_cannot_hide_receipt_after_other_worker_crashes(
    tmp_path, monkeypatch
):
    path = tmp_path / "state.sqlite"
    first, second = offline_agent(path), offline_agent(path)
    action_id = pending(first)
    failed, committed = Event(), Event()
    original = first.mock_platforms.actions.complete

    def delayed_failure(*args):
        failed.set()
        assert committed.wait(10)
        original(*args)

    def crash_after_commit(*args):
        raise RuntimeError("worker stopped before ledger completion")

    monkeypatch.setattr(first.mock_platforms.actions, "complete", delayed_failure)
    monkeypatch.setattr(second.mock_platforms.actions, "complete", crash_after_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        loser = pool.submit(
            invoke, first, "确认执行", action_id=action_id, fault_id="f_403"
        )
        assert failed.wait(10)
        try:
            with pytest.raises(RuntimeError, match="worker stopped"):
                invoke(second, "确认执行", action_id=action_id)
        finally:
            committed.set()
        loser.result(timeout=10)
    restarted = offline_agent(path)
    assert invoke(restarted, "重试执行", action_id=action_id)["success"]
    assert restarted.mock_platforms.actions.get(action_id, CTX)["status"] == "success"
    assert quantity(path) == 10


@pytest.mark.parametrize("expire", [False, True])
def test_confirmation_reconciles_when_other_worker_finishes_before_running(
    tmp_path, monkeypatch, expire
):
    path = tmp_path / "state.sqlite"
    first, second = offline_agent(path), offline_agent(path)
    action_id = pending(first)
    original = first.mock_platforms.actions.running

    def raced_running(*args):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(invoke, second, "确认执行", action_id=action_id).result(
                timeout=10
            )["success"]
        if expire:
            with sqlite3.connect(path) as db:
                db.execute(
                    "UPDATE actions SET expires_at=0 WHERE action_id=?", (action_id,)
                )
        return original(*args)

    monkeypatch.setattr(first.mock_platforms.actions, "running", raced_running)
    result = invoke(first, "确认执行", action_id=action_id)
    assert result["success"], result
    assert quantity(path) == 10
