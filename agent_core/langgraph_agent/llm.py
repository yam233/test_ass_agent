"""Compatibility import; the shared client does not depend on LangGraph."""
from agent_core.model_client import DeepSeekLLM

__all__ = ["DeepSeekLLM"]
