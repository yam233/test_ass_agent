"""Short-term and long-term memory adapters."""
from typing import Any, Dict, List, Optional

from agent_core.langgraph_agent.compat import Chroma, ConversationBufferWindowMemory


class ShortTermMemory:
    def __init__(self, turns: int = 6):
        self.turns = turns
        self._fallback: Dict[str, List[Dict[str, Any]]] = {}
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._memory = None
        if ConversationBufferWindowMemory is not None:
            try:  # pragma: no cover - depends on optional package version
                self._memory = ConversationBufferWindowMemory(k=turns, return_messages=True)
            except Exception:
                self._memory = None

    def key_for(self, context: Optional[Dict[str, Any]] = None) -> str:
        context = context or {}
        operator = context.get("operator") or "anonymous"
        session_id = context.get("session_id") or "default"
        return f"{operator}:{session_id}"

    def add_turn(self, user_input: str, output: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> None:
        if self._memory is not None:
            try:  # pragma: no cover
                self._memory.save_context({"input": user_input}, {"output": output.get("message", "")})
            except Exception:
                pass
        key = self.key_for(context)
        turns = self._fallback.setdefault(key, [])
        turns.append({"input": user_input, "output": output})
        self._fallback[key] = turns[-self.turns:]

    def recent(self, context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return list(self._fallback.get(self.key_for(context), [])[-self.turns:])

    def set_pending(self, context: Optional[Dict[str, Any]], pending: Dict[str, Any]) -> None:
        self._pending[self.key_for(context)] = pending

    def get_pending(self, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return self._pending.get(self.key_for(context))

    def clear_pending(self, context: Optional[Dict[str, Any]] = None) -> None:
        self._pending.pop(self.key_for(context), None)


class SkillVectorIndex:
    """Chroma-backed skill metadata index with an in-memory fallback."""

    def __init__(self, persist_directory: str = ".agent_memory/chroma"):
        self.persist_directory = persist_directory
        self._entries: List[Dict[str, Any]] = []
        self._store = None
        if Chroma is not None:
            try:  # pragma: no cover - optional embedding setup varies by env
                self._store = Chroma(collection_name="skill_metadata", persist_directory=persist_directory)
            except Exception:
                self._store = None

    def upsert(self, entries: List[Dict[str, Any]]) -> None:
        self._entries.extend(entries)

    def search(self, keyword: str, limit: int = 5) -> List[Dict[str, Any]]:
        keyword = (keyword or "").lower()
        if not keyword:
            return self._entries[:limit]
        results = [
            item for item in self._entries
            if keyword in " ".join(str(v).lower() for v in item.values())
        ]
        return results[:limit]
