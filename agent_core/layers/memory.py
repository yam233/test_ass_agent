"""Short-term and long-term Agent memory."""
import json
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional


class ShortTermMemory:
    """In-process memory for recent turns and task progress."""

    def __init__(self, max_turns: int = 8, ttl_seconds: int = 900):
        self.max_turns = max_turns
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, Dict[str, Any]] = {}

    def get_history(self, session_key: str) -> List[Dict[str, Any]]:
        self._cleanup()
        item = self._store.get(session_key, {})
        return list(item.get("turns", []))

    def append_turn(self, session_key: str, turn: Dict[str, Any]):
        self._cleanup()
        current = self._store.get(session_key, {"turns": deque(maxlen=self.max_turns)})
        turns = current.get("turns")
        if not isinstance(turns, deque):
            turns = deque(list(turns or [])[-self.max_turns:], maxlen=self.max_turns)
        turn["timestamp"] = int(time.time())
        turns.append(turn)
        self._store[session_key] = {
            "updated_at": time.time(),
            "turns": turns,
            "progress": current.get("progress", {})
        }

    def set_progress(self, session_key: str, progress: Dict[str, Any]):
        current = self._store.get(session_key, {"turns": deque(maxlen=self.max_turns)})
        current["progress"] = progress
        current["updated_at"] = time.time()
        self._store[session_key] = current

    def get_progress(self, session_key: str) -> Dict[str, Any]:
        self._cleanup()
        return dict(self._store.get(session_key, {}).get("progress", {}))

    def _cleanup(self):
        now = time.time()
        expired = [
            key for key, value in self._store.items()
            if now - value.get("updated_at", now) > self.ttl_seconds
        ]
        for key in expired:
            self._store.pop(key, None)


class LongTermMemory:
    """
    Append-only local memory for skill index snapshots and operation history.

    Default path is gitignored.
    """

    def __init__(self, root: str = ".agent_memory"):
        self.root = Path(root)
        self.root.mkdir(exist_ok=True)
        self.skill_index_path = self.root / "skill_index.json"
        self.operation_log_path = self.root / "operations.jsonl"

    def save_skill_index(self, business_code: str, skills: List[Dict[str, Any]]):
        snapshot = {
            "business_code": business_code,
            "updated_at": int(time.time()),
            "skills": [
                {
                    "skill_name": item.get("skill_name"),
                    "display_name": item.get("display_name"),
                    "skill_type": item.get("skill_type"),
                    "description": item.get("description"),
                }
                for item in skills
            ]
        }
        with open(self.skill_index_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

    def append_operation(self, record: Dict[str, Any]):
        payload = dict(record)
        payload.setdefault("timestamp", int(time.time()))
        with open(self.operation_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def load_skill_index(self) -> Optional[Dict[str, Any]]:
        if not self.skill_index_path.exists():
            return None
        with open(self.skill_index_path, "r", encoding="utf-8") as f:
            return json.load(f)
