"""Optional LangChain/LangGraph compatibility shims.

The project can run its architecture tests without installing the optional
agent stack. Production deployments should install the packages declared in
requirements.txt and will use the real classes automatically.
"""
from typing import Any, Callable, Dict, Optional


try:  # pragma: no cover - exercised when optional deps are installed
    from langchain.tools import BaseTool as LangChainBaseTool
except Exception:  # pragma: no cover - fallback is covered by local tests
    LangChainBaseTool = None


class FallbackBaseTool:
    """Small subset of LangChain BaseTool used by this project."""

    name: str = ""
    description: str = ""

    def __init__(self, **kwargs: Any):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        return self._run(*args, **kwargs)

    def invoke(self, input: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        payload = input if isinstance(input, dict) else {}
        payload.update(kwargs)
        return self._run(**payload)


BaseTool = LangChainBaseTool or FallbackBaseTool


try:  # pragma: no cover
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover
    END = "__end__"
    StateGraph = None


try:  # pragma: no cover
    from langchain.memory import ConversationBufferWindowMemory
except Exception:  # pragma: no cover
    ConversationBufferWindowMemory = None


try:  # pragma: no cover
    from langchain_chroma import Chroma
except Exception:  # pragma: no cover
    try:
        from langchain.vectorstores import Chroma
    except Exception:
        Chroma = None


def has_langgraph() -> bool:
    return StateGraph is not None


def build_state_graph(state_type: Any, nodes: Dict[str, Callable], edges: Dict[str, str]):
    """Build a LangGraph app when available, otherwise return None."""
    if StateGraph is None:
        return None
    graph = StateGraph(state_type)
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.set_entry_point("parse")
    for source, target in edges.items():
        graph.add_edge(source, END if target == "END" else target)
    return graph.compile()


def build_branching_state_graph(
    state_type: Any,
    nodes: Dict[str, Callable],
    edges: Dict[str, str],
    conditional_edges: Dict[str, tuple[Callable, Dict[str, str]]],
):
    """Build a branching LangGraph app when available, otherwise return None."""
    if StateGraph is None:
        return None
    graph = StateGraph(state_type)
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.set_entry_point("parse")
    for source, target in edges.items():
        graph.add_edge(source, END if target == "END" else target)
    for source, (router, path_map) in conditional_edges.items():
        graph.add_conditional_edges(
            source,
            router,
            {key: (END if value == "END" else value) for key, value in path_map.items()},
        )
    return graph.compile()
