"""
Agent 管理器模块

职责分离：
- IntentManager: 意图识别管理
- ParameterManager: 参数提取与适配管理
"""
from .intent_manager import IntentManager
from .parameter_manager import ParameterManager

__all__ = ["IntentManager", "ParameterManager"]
