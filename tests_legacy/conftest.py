import pytest

@pytest.fixture(autouse=True)
def offline_legacy(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "offline")
