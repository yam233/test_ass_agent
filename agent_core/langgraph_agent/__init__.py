"""Lazy optional graph facade; native workflows do not load LangGraph."""
__all__ = ["LangGraphAgent"]

def __getattr__(name):
    if name == "LangGraphAgent":
        from .graph import LangGraphAgent
        return LangGraphAgent
    raise AttributeError(name)
