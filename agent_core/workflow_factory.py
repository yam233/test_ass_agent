"""Default dependency assembly for the single-host workflow runtime.

This is the only place that chooses the default model and concrete stores/platform.
It does not load legacy agents, start workers, or call remote services.
"""
from agent_core.model_client import DeepSeekLLM
from agent_core.workflow_model import NativeModel
from agent_core.workflow_platform import WorkflowPlatform
from agent_core.workflow_rules import RuleModel
from agent_core.workflow_store import WorkflowStore


def build_model():
    client = DeepSeekLLM()
    return RuleModel() if client.mode == "offline" else NativeModel(client)


def build_dependencies(path, model=None):
    return (
        WorkflowPlatform(path),
        WorkflowStore(path),
        build_model() if model is None else model,
    )
