"""通用工具层"""

__all__ = ["LLMClient", "ConfigLoader", "ResultFormatter"]


def __getattr__(name):
    if name == "LLMClient":
        from .llm_client import LLMClient
        return LLMClient
    if name == "ConfigLoader":
        from .config_loader import ConfigLoader
        return ConfigLoader
    if name == "ResultFormatter":
        from .result_formatter import ResultFormatter
        return ResultFormatter
    raise AttributeError(f"module 'utils' has no attribute {name!r}")
