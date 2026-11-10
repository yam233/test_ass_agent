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
