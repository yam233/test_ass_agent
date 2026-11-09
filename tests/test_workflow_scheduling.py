import asyncio
import importlib.util
import time
import pytest
from tests.test_workflow import CTX, run
from agent_core.workflow_store import Budget


@pytest.fixture(autouse=True)
def offline_workers(monkeypatch):
    # Spawned workers must never inherit a developer's paid model configuration.
    monkeypatch.setenv("LLM_MODE", "offline")


def scheduler(path, **kwargs):
    assert importlib.util.find_spec(
        "agent_core.workflow_runner"
    ), "supervised scheduler missing"
    from agent_core.workflow_runner import WorkflowRunner

    return WorkflowRunner(path, **kwargs)


def test_eight_tasks_share_two_slots_and_survive_restart(tmp_path):
    async def scenario():
        runner = scheduler(tmp_path / "db")
        states = [
            runner.jobs.submit("查询用户123的礼物记录", {**CTX, "request_id": str(i)}, Budget())
            for i in range(8)
        ]
        await runner.start()
        try:
            result = await asyncio.wait_for(
                asyncio.gather(*(runner.wait(s["task_id"], CTX) for s in states)), 20
            )
            assert all(s["status"] == "completed" for s in result)
            assert runner.max_observed <= 2
        finally:
            await runner.stop()
        restarted = scheduler(tmp_path / "db")
        await restarted.start()
        try:
            assert all(
                restarted.jobs.store.get(s["task_id"], CTX)["status"] == "completed"
                for s in states
            )
        finally:
            await restarted.stop()

    run(scenario())


def test_service_sigterm_preserves_approval_and_restarts_without_duplicate(tmp_path):
    import os
    import socket
    import subprocess
    import sys
    import httpx
    from pathlib import Path
    from agent_core.workflow_store import WorkflowStore

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    path = tmp_path / "signal.sqlite"
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "api.offline_server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "error",
    ]
    env = {**os.environ, "LLM_MODE": "offline", "MOCK_DB_PATH": str(path)}

    def launch(client):
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                assert process.poll() is None, "server exited during startup"
                try:
                    if client.get("/").status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            pytest.fail("server did not start")
        except BaseException:
            process.kill()
            process.wait()
            raise

    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        process = launch(client)
        try:
            response = client.post(
                "/workflows", json={"user_input": "给用户123发10个礼物301到背包", "context": CTX}
            )
            response.raise_for_status()
            state = response.json()
            assert state["status"] == "approval_wait"
        finally:
            process.terminate()
            process.wait(timeout=15)
        process = launch(client)
        try:
            response = client.post(
                f"/workflows/{state['task_id']}/resume",
                json={
                    "context": CTX,
                    "action_id": state["pending"]["action_id"],
                    "decision": "approve",
                },
            )
            response.raise_for_status()
            assert response.json()["status"] == "completed"
            with WorkflowStore(path).db.connection() as db:
                assert (
                    db.execute("SELECT count(*) FROM platform_receipts").fetchone()[0]
                    == 1
                )
                import json

                rows = db.execute("SELECT payload FROM gifts").fetchall()
                assert sum(json.loads(row[0])["quantity"] for row in rows) == 10
        finally:
            process.terminate()
            process.wait(timeout=15)


def test_hung_tool_is_terminated_before_deadline_and_no_write(tmp_path):
    async def scenario():
        runner = scheduler(tmp_path / "db", tool_timeout=0.2)
        await runner.start()
        try:
            state = runner.jobs.submit(
                "给用户123发10个礼物301到背包", {**CTX, "fault_id": "f_tool_hang"}, Budget()
            )
            state = await runner.wait(state["task_id"], CTX)
            start = time.monotonic()
            runner.jobs.resume(
                state["task_id"],
                CTX,
                action_id=state["pending"]["action_id"],
                decision="approve",
            )
            state = await asyncio.wait_for(runner.wait(state["task_id"], CTX), 6)
            assert state["stop_reason"] == "tool_timeout"
            assert time.monotonic() - start < 3
            with runner.jobs.store.db.connection() as db:
                assert db.execute("SELECT count(*) FROM gifts").fetchone()[0] == 0
        finally:
            await runner.stop()

    run(scenario())


def test_shutdown_reaps_workers_after_scheduler_loop_error(tmp_path):
    async def scenario():
        runner = scheduler(tmp_path / "db")
        runner.jobs.submit("查询用户123的礼物记录", {**CTX, "fault_id": "f_tool_hang"}, Budget())
        original = runner._dispatch

        def broken_dispatch():
            original()
            raise RuntimeError("injected dispatch failure")

        runner._dispatch = broken_dispatch
        await runner.start()
        while not runner._task.done():
            await asyncio.sleep(0.01)
        processes = [p for p, _ in runner.active.values()]
        assert processes
        try:
            with pytest.raises(RuntimeError, match="injected dispatch failure"):
                await runner.stop(grace=0.01)
            assert all(p.poll() is not None for p in processes)
        finally:
            for process in processes:
                if process.poll() is None:
                    import os, signal

                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()

    run(scenario())


def test_submit_api_responds_while_tool_is_blocked_and_cancel_stops_future_steps(
    tmp_path,
):
    import httpx
    from api.offline_server import create_app
    from agent_core.workflow import WorkflowRuntime

    async def scenario():
        app = create_app(workflow=WorkflowRuntime(tmp_path / "db"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/workflows",
                json={
                    "user_input": "查询用户123的礼物记录",
                    "dispatch": "queued",
                    "context": {**CTX, "fault_id": "f_tool_hang"},
                },
            )
            assert response.status_code == 202
            state = response.json()
            task_id = state["task_id"]
            status = await asyncio.wait_for(
                client.post(f"/workflows/{task_id}/status", json={"context": CTX}), 1
            )
            assert status.status_code == 200
            result = await client.post(
                f"/workflows/{task_id}/cancel", json={"context": CTX}
            )
            assert result.status_code in {200, 202}
            final = await asyncio.wait_for(app.state.runner.wait(task_id, CTX), 6)
            assert final["status"] == "cancelled"
        await app.state.runner.stop()

    run(scenario())


@pytest.mark.parametrize("fault", ["f_crash_before_receipt", "f_crash_after_commit"])
def test_isolated_write_crash_reconciles_without_duplicate(tmp_path, fault):
    from agent_core.workflow import WorkflowRuntime
    from tests.test_workflow import SEED, SequenceModel, call, approve

    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel([call("seed_test_data", SEED), {"final": "done"}]),
        retry_delays=(0, 0),
    )
    state = run(rt.start("seed", {**CTX, "fault_id": fault, "fault_count": 1}))
    state = approve(rt, state)
    assert state["status"] == "completed"
    assert len(rt.platform.snapshot("gifts")) == 1
    with rt.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM platform_receipts").fetchone()[0] == 1


def test_cancel_after_commit_reports_effect_and_invalidates_remaining_work(tmp_path):
    from agent_core.workflow import WorkflowRuntime
    from tests.test_workflow import SEED, SequenceModel, call

    rt = WorkflowRuntime(
        tmp_path / "db",
        model=SequenceModel(
            [call("seed_test_data", SEED), call("query_data", {"table": "gifts"})]
        ),
    )
    state = run(rt.start("seed", CTX))
    aid = state["pending"]["action_id"]
    rt.platform.actions.approve(aid, CTX)
    # Simulate committed platform transaction before parent checkpoint completion.
    receipt = rt.platform.execute("seed_test_data", SEED, {**CTX, "action_id": aid})
    assert receipt["success"]
    rt.store.request_cancel(state["task_id"], CTX)
    final = run(rt.resume(state["task_id"], CTX))
    assert final["status"] == "cancelled" and final["cancelled_after_commit"]
    assert final["result"]["data"]["actual"] == 10 and len(final["steps"]) == 1
    assert len(rt.platform.snapshot("gifts")) == 1


def test_shutdown_and_restart_recover_inflight_action_once(tmp_path):
    async def scenario():
        runner = scheduler(tmp_path / "db", tool_timeout=3)
        await runner.start()
        state = runner.jobs.submit(
            "给用户123发10个礼物301到背包，然后查询核验",
            {**CTX, "fault_id": "f_tool_hang", "fault_count": 1},
            Budget(),
        )
        state = await runner.wait(state["task_id"], CTX)
        runner.jobs.resume(
            state["task_id"],
            CTX,
            action_id=state["pending"]["action_id"],
            decision="approve",
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            observed = runner.jobs.store.get(state["task_id"], CTX)
            if (observed.get("pending") or {}).get("attempts") == 1:
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("worker never started")
        await runner.stop(grace=0.01)
        restarted = scheduler(tmp_path / "db", tool_timeout=0.5)
        await restarted.start()
        try:
            final = await asyncio.wait_for(restarted.wait(state["task_id"], CTX), 8)
            assert final["status"] == "completed", final.get("result")
            with restarted.jobs.store.db.connection() as db:
                assert db.execute("SELECT count(*) FROM gifts").fetchone()[0] == 1
                assert (
                    db.execute("SELECT count(*) FROM platform_receipts").fetchone()[0]
                    == 1
                )
        finally:
            await restarted.stop()

    run(scenario())


def test_mixed_http_dispatch_modes_share_pool(tmp_path):
    import httpx
    from api.offline_server import create_app
    from agent_core.workflow import WorkflowRuntime

    async def scenario():
        app = create_app(workflow=WorkflowRuntime(tmp_path / "db"))
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        *[
                            client.post(
                                "/workflows",
                                json={
                                    "user_input": "查询用户123的礼物记录",
                                    "dispatch": "inline" if i % 2 else "queued",
                                    "context": {**CTX, "request_id": str(i)},
                                },
                            )
                            for i in range(8)
                        ]
                    ),
                    20,
                )
                assert [r.status_code for r in responses] == [202, 200] * 4
                await asyncio.gather(
                    *(
                        app.state.runner.wait(r.json()["task_id"], CTX)
                        for r in responses
                    )
                )
                assert app.state.runner.max_observed <= 2
        finally:
            if app.state.runner:
                await app.state.runner.stop()

    run(scenario())


def test_recovery_never_steals_direct_sdk_task_lock(tmp_path):
    from agent_core.workflow import WorkflowRuntime
    from tests.test_workflow import SequenceModel

    rt = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    state = rt.store.create("read", CTX, Budget())
    runner = scheduler(tmp_path / "db")
    with rt.store.lock(state["task_id"]):
        runner.recover()
        with rt.store.db.connection() as db:
            assert db.execute("SELECT count(*) FROM workflow_jobs").fetchone()[0] == 0
    runner.recover()
    with rt.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_jobs").fetchone()[0] == 1
