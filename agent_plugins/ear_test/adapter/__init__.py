"""AI测试助手 - 适配器实现"""
from .test_mcp_adapter import TestMCPAdapter
from .test_wechat_adapter import TestWechatAdapter

__all__ = ["TestMCPAdapter", "TestWechatAdapter"]
