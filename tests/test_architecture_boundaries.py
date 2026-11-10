import asyncio
import pytest
from agent_core.action_store import ActionError
from tests.test_workflow import CTX, SEED, SequenceModel, call, run


def test_native_adapter_uses_public_client_contract():
    from agent_core.workflow_model import NativeModel

    class Client:
        mode = "remote"

        def setting(self, key):
            return {"model": "stub", "base_url": "https://example.test/v1"}[key]

        async def completion(self, messages, **options):
            assert options["parallel_tool_calls"] is False
            return {
                "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 2},
            }

    model = NativeModel(Client())
    result = run(model.next([{"role": "user", "content": "read"}], CTX, 128))
    assert result["final"] == "done" and result["model"] == "stub"
    from agent_core.model_call import artifact

    assert artifact(model, 128)["model_config"]["model"] == "stub"


def test_model_client_keeps_legacy_import_and_private_aliases(tmp_path):
    from agent_core.model_client import DeepSeekLLM
    from agent_core.langgraph_agent.llm import DeepSeekLLM as LegacyLLM
    from agent_core.layers.local_config import LocalConfigLayer

    assert LegacyLLM is DeepSeekLLM
    client = DeepSeekLLM(LocalConfigLayer(str(tmp_path / "empty")))
    assert (
        client.setting("missing", "fallback")
        == client._setting("missing", "fallback")
        == "fallback"
    )

    async def transport(*args, **kwargs):
        return {"result": "test"}

    client._completion = transport
    assert run(client.completion([])) == {"result": "test"}


def test_factory_respects_default_modes_and_custom_injection(tmp_path, monkeypatch):
    from agent_core import workflow_factory
    from agent_core.workflow import WorkflowRuntime
    from agent_core.workflow_model import NativeModel
    from agent_core.workflow_rules import RuleModel

    monkeypatch.setenv("LLM_MODE", "offline")
    assert isinstance(workflow_factory.build_model(), RuleModel)
    monkeypatch.setenv("LLM_MODE", "remote")
    assert isinstance(workflow_factory.build_model(), NativeModel)

    def unexpected():
        raise AssertionError("explicit model caused default model construction")

    monkeypatch.setattr(workflow_factory, "build_model", unexpected)
    explicit = SequenceModel(
        [call("query_data", {"table": "gifts"}), {"final": "done"}]
    )
    runtime = WorkflowRuntime(tmp_path / "db", model=explicit)
    assert runtime.model is explicit
    assert run(runtime.start("read", CTX))["status"] == "completed"


def test_shared_request_validation_matches_sdk_and_queue(tmp_path):
    from agent_core.workflow_contracts import validate_request
    from agent_core.workflow_jobs import JobStore
    from agent_core.workflow import WorkflowRuntime

    with pytest.raises(ActionError) as error:
        validate_request("read", {**CTX, "env": "invalid"})
    assert error.value.code == "BAD_ARGS"
    jobs = JobStore(tmp_path / "db")
    runtime = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    from agent_core.workflow_store import Budget

    for operation in (
        lambda: validate_request("", CTX),
        lambda: jobs.submit("", CTX, Budget()),
        lambda: run(runtime.start("", CTX)),
    ):
        with pytest.raises(ValueError):
            operation()
    with jobs.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_tasks").fetchone()[0] == 0


def committed_task(path, context=CTX):
    from agent_core.workflow import WorkflowRuntime

    runtime = WorkflowRuntime(
        path, model=SequenceModel([call("seed_test_data", SEED), {"final": "done"}])
    )
    state = run(runtime.start("seed", context))
    aid = state["pending"]["action_id"]
    state = run(
        runtime.resume(state["task_id"], context, action_id=aid, decision="approve")
    )
    assert state["status"] == "completed"
    return runtime, state, aid


def test_receipt_repository_enforces_task_and_scope_boundaries(tmp_path):
    runtime, first, aid = committed_task(tmp_path / "db")
    _, second, other = committed_task(tmp_path / "db")
    store = runtime.platform.actions
    assert store.receipt(aid, CTX)["data"]["actual"] == 10
    assert set(store.task_receipts(first["task_id"], CTX)) == {aid}
    assert set(store.task_receipts(second["task_id"], CTX)) == {other}
    for context in (
        {**CTX, "operator": "bob"},
        {**CTX, "session_id": "other"},
        {**CTX, "env": "dev"},
    ):
        with pytest.raises(ActionError):
            store.receipt(aid, context)
        assert store.task_receipts(first["task_id"], context) == {}
    # Public task IDs must not be interpreted as SQL patterns.
    assert store.task_receipts("%", CTX) == {}
    assert store.task_receipts(first["task_id"][:-1], CTX) == {}


def test_cancel_repository_keeps_audit_and_state_atomic(tmp_path, monkeypatch):
    from agent_core.workflow import WorkflowRuntime

    runtime = WorkflowRuntime(
        tmp_path / "db", model=SequenceModel([call("seed_test_data", SEED)])
    )
    state = run(runtime.start("seed", CTX))
    aid = state["pending"]["action_id"]
    store = runtime.platform.actions
    original = __import__(
        "agent_core.action_store", fromlist=["audit_action"]
    ).audit_action

    def failed_audit(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr("agent_core.action_store.audit_action", failed_audit)
    with pytest.raises(RuntimeError):
        store.cancel_action(aid, CTX)
    assert store.get(aid, CTX)["status"] == "pending"
    monkeypatch.setattr("agent_core.action_store.audit_action", original)
    with pytest.raises(ActionError):
        store.cancel_action(aid, {**CTX, "operator": "bob"})
    store.cancel_action(aid, CTX)
    assert store.get(aid, CTX)["status"] == "cancelled"
    with store.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM workflow_audit WHERE action_id=? AND event='cancel'",
                (aid,),
            ).fetchone()[0]
            == 1
        )
    assert not runtime.platform.snapshot("gifts")


def test_cancel_repository_preserves_committed_receipt_and_result(tmp_path):
    runtime, _, aid = committed_task(tmp_path / "db")
    store = runtime.platform.actions
    before = store.get(aid, CTX)
    assert store.cancel_action(aid, CTX) is False
    assert store.get(aid, CTX) == before
    assert store.receipt(aid, CTX)["data"]["actual"] == 10


def test_health_describes_primary_runtime_without_initializing_legacy(
    tmp_path, monkeypatch
):
    import httpx
    from api.offline_server import create_app
    from agent_core.workflow import WorkflowRuntime

    def unexpected(*args, **kwargs):
        raise AssertionError("health must not initialize legacy agent")

    monkeypatch.setattr("agent_core.offline_runtime.build_offline_agent", unexpected)
    runtime = WorkflowRuntime(tmp_path / "db", model=SequenceModel([]))
    app = create_app(workflow=runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in ("/", "/health"):
                response = await client.get(path)
                assert response.status_code == 200
                data = response.json()
                assert data["primary_endpoint"] == "/workflows"
                assert data["orchestrator"] == "workflow_runtime"
                assert data["llm_mode"] == "custom"
                assert data["compatibility"]["initialized"] is False
                assert data["compatibility"]["orchestrator"] is None

    run(scenario())
    assert app.state.agent is None


def test_health_separates_initialized_legacy_and_primary_models(tmp_path):
    import httpx
    from types import SimpleNamespace
    from api.offline_server import create_app
    from agent_core.workflow import WorkflowRuntime
    from agent_core.workflow_rules import RuleModel

    runtime = WorkflowRuntime(tmp_path / "db", model=RuleModel())
    legacy = SimpleNamespace(llm=SimpleNamespace(mode="remote"), _graph=object())
    app = create_app(workflow=runtime, agent=legacy)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            data = (await client.get("/health")).json()
            assert data["llm_mode"] == "offline"
            assert data["orchestrator"] == "workflow_runtime"
            assert data["compatibility"]["initialized"] is True
            assert data["compatibility"]["orchestrator"] == "langgraph"
            assert data["compatibility"]["llm_mode"] == "remote"

    run(scenario())
