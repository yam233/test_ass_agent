"""Keep inherited architecture guards offline without disabling transport mock tests."""
import pytest

@pytest.fixture(autouse=True)
def architecture_tests_never_use_remote_model(request, monkeypatch):
    if request.node.path.name == 'test_agent_architecture_guards.py':
        monkeypatch.setenv('LLM_MODE','offline')
