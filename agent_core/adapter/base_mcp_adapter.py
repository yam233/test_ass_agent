"""MCP适配器基类"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseMCPAdapter(ABC):
    """MCP适配器基类，业务层继承实现"""
    
    @abstractmethod
    def adapt_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """适配请求"""
        pass
    
    @abstractmethod
    def adapt_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """适配响应"""
        pass
