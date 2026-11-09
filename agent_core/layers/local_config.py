"""Local-only configuration layer for secrets and operator policy."""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class LocalConfigLayer:
    """
    Load secrets and operator policy from local files outside tracked config.

    Expected file: config/local/agent_secrets.json
    This path is ignored by git. Environment variables still win.
    """

    DEFAULT_PATH = Path("config/local/agent_secrets.json")

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else self.DEFAULT_PATH
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def get_secret(self, key: str, env_name: Optional[str] = None, default: Any = None) -> Any:
        if env_name and os.getenv(env_name):
            return os.getenv(env_name)
        if os.getenv(key):
            return os.getenv(key)
        secrets = self._config.get("secrets", {})
        return secrets.get(key) or secrets.get(env_name or key.upper()) or default

    def get_operator_policy(self) -> Dict[str, Any]:
        policy = self._config.get("operator_policy", {})
        return policy if isinstance(policy, dict) else {}

    def get_gitlab_config(self) -> Dict[str, Any]:
        config = self._config.get("gitlab", {})
        return config if isinstance(config, dict) else {}

    def redacted(self) -> Dict[str, Any]:
        """Return a safe view for diagnostics."""
        safe = dict(self._config)
        if "secrets" in safe:
            safe["secrets"] = {k: "***" for k in safe.get("secrets", {})}
        if "gitlab" in safe and isinstance(safe["gitlab"], dict):
            safe["gitlab"] = {
                k: ("***" if "token" in k.lower() else v)
                for k, v in safe["gitlab"].items()
            }
        return safe
