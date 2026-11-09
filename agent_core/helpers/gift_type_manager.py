"""
礼物类型管理器 - 配置驱动的礼物类型规则
"""
import json
import os
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class GiftTypeManager:
    """礼物类型管理器 - 从配置文件加载规则"""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化 - 加载配置"""
        if self._config is None:
            self._load_config()
    
    def _load_config(self):
        """加载礼物类型配置"""
        try:
            config_path = os.path.join(
                os.path.dirname(__file__),
                "../../config/business/ear_test/gift_type_rules.json"
            )
            config_path = os.path.abspath(config_path)
            
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
            
            logger.info(f"礼物类型配置加载成功: {len(self._config['gift_types'])} 种类型")
        except Exception as e:
            logger.error(f"加载礼物类型配置失败: {e}")
            # 使用默认配置
            self._config = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置（兜底）"""
        return {
            "gift_types": {
                "2": {
                    "name": "用户专属礼物",
                    "support_exclusive_tab": True,
                    "support_backpack": False,
                    "target_param": "user_id",
                    "target_type": "user"
                },
                "3": {
                    "name": "免费礼物",
                    "support_exclusive_tab": False,
                    "support_backpack": True,
                    "target_param": "user_id",
                    "target_type": "user"
                },
                "4": {
                    "name": "白给礼物",
                    "support_exclusive_tab": False,
                    "support_backpack": True,
                    "target_param": "user_id",
                    "target_type": "user"
                },
                "7": {
                    "name": "直播间专属礼物",
                    "support_exclusive_tab": True,
                    "support_backpack": False,
                    "target_param": "room_id",
                    "target_type": "room"
                },
                "8": {
                    "name": "随机礼物",
                    "support_exclusive_tab": True,
                    "support_backpack": False,
                    "target_param": "user_id",
                    "target_type": "user_or_room"
                }
            },
            "validation": {
                "id_range": {
                    "min": 1,
                    "max": 99999999999
                }
            }
        }
    
    def get_gift_type_prefix(self, gift_id: int) -> str:
        """获取礼物ID的类型前缀"""
        return str(gift_id)[0] if gift_id else ""
    
    def get_gift_type_rule(self, gift_id: int) -> Optional[Dict[str, Any]]:
        """
        获取礼物类型规则
        
        Args:
            gift_id: 礼物ID
            
        Returns:
            礼物类型规则字典，如果不存在返回None
        """
        prefix = self.get_gift_type_prefix(gift_id)
        return self._config["gift_types"].get(prefix)
    
    def get_gift_type_name(self, gift_id: int) -> str:
        """获取礼物类型名称"""
        rule = self.get_gift_type_rule(gift_id)
        return rule["name"] if rule else "未知类型"
    
    def supports_exclusive_tab(self, gift_id: int) -> bool:
        """判断礼物是否支持发放到专属tab"""
        rule = self.get_gift_type_rule(gift_id)
        return rule["support_exclusive_tab"] if rule else False
    
    def supports_backpack(self, gift_id: int) -> bool:
        """判断礼物是否支持发放到背包"""
        rule = self.get_gift_type_rule(gift_id)
        return rule["support_backpack"] if rule else False
    
    def get_target_param(self, gift_id: int) -> str:
        """
        获取目标参数名称 (user_id 或 room_id)
        
        Args:
            gift_id: 礼物ID
            
        Returns:
            参数名称，默认返回 "user_id"
        """
        rule = self.get_gift_type_rule(gift_id)
        return rule["target_param"] if rule else "user_id"
    
    def get_target_type(self, gift_id: int) -> str:
        """
        获取目标类型 (user, room, user_or_room)
        
        Args:
            gift_id: 礼物ID
            
        Returns:
            目标类型
        """
        rule = self.get_gift_type_rule(gift_id)
        return rule["target_type"] if rule else "user"
    
    def validate_gift_id_for_exclusive_tab(
        self, 
        gift_id: int, 
        user_input: str
    ) -> Optional[str]:
        """
        验证礼物ID是否支持发放到专属tab
        
        Args:
            gift_id: 礼物ID
            user_input: 用户原始输入
            
        Returns:
            错误提示信息，如果验证通过返回None
        """
        # 检查用户是否想发放到专属tab
        if "专属" not in user_input and "exclusive" not in user_input.lower():
            return None
        
        rule = self.get_gift_type_rule(gift_id)
        
        if not rule:
            # 获取所有支持专属tab的类型
            supported_types = [
                prefix for prefix, r in self._config["gift_types"].items()
                if r["support_exclusive_tab"]
            ]
            supported_str = "、".join(supported_types)
            return f"礼物ID {gift_id} 格式不正确。专属礼物ID应以 {supported_str} 开头。"
        
        if not rule["support_exclusive_tab"]:
            # 获取所有支持专属tab的类型说明
            supported_types = [
                f"{r['name']}({prefix}开头)"
                for prefix, r in self._config["gift_types"].items()
                if r["support_exclusive_tab"]
            ]
            supported_str = "、".join(supported_types)
            return f"礼物ID {gift_id} 是{rule['name']}，不支持发放到专属tab。只有 {supported_str} 才支持发放到专属tab。"
        
        return None
    
    def get_id_range(self) -> Tuple[int, int]:
        """获取ID范围"""
        validation = self._config.get("validation", {}).get("id_range", {})
        return validation.get("min", 1), validation.get("max", 99999999999)
    
    def get_all_gift_types(self) -> Dict[str, Dict[str, Any]]:
        """获取所有礼物类型配置"""
        return self._config["gift_types"]
    
    def reload_config(self):
        """重新加载配置（用于配置更新后刷新）"""
        self._config = None
        self._load_config()


# 全局单例
gift_type_manager = GiftTypeManager()
