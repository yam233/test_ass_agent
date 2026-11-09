"""企微适配器基类"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseWechatAdapter(ABC):
    """企微适配器基类，业务层继承实现"""
    
    @abstractmethod
    def adapt_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """适配消息"""
        pass
    
    @abstractmethod
    def format_reply(self, data: Dict[str, Any]) -> str:
        """格式化回复"""
        pass
