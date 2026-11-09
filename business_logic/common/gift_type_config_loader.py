"""
礼物类型配置加载器
用于加载礼物类型规则配置
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class GiftTypeConfigLoader:
    """礼物类型配置加载器"""
    
    _config_cache: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def load_config(cls, business_code: str = "ear_test") -> Dict[str, Any]:
        """
        加载礼物类型配置
        
        Args:
            business_code: 业务代码
            
        Returns:
            配置字典
        """
        if business_code not in cls._config_cache:
            try:
                from utils.config_loader_v2 import ConfigLoaderV2
                cls._config_cache[business_code] = ConfigLoaderV2.load_business_config(
                    business_code,
                    "gift_type_rules.json"
                )
                logger.info(f"✓ 礼物类型配置已加载 (business: {business_code})")
            except Exception as e:
                logger.warning(f"加载礼物类型配置失败 (business: {business_code}): {e}")
                # 返回默认配置
                cls._config_cache[business_code] = cls._get_default_config()
        
        return cls._config_cache[business_code]
    
    @classmethod
    def _get_default_config(cls) -> Dict[str, Any]:
        """
        获取默认配置（当配置文件加载失败时使用）
        
        Returns:
            默认配置字典
        """
        return {
            "gift_types": {
                "1": {
                    "name": "常规礼物",
                    "support_exclusive_tab": False,
                    "support_backpack": False,
                    "target_param": "user_id",
                    "target_type": "user",
                    "description": "普通礼物"
                },
                "2": {
                    "name": "用户专属礼物",
                    "support_exclusive_tab": True,
                    "support_backpack": False,
                    "target_param": "user_id",
                    "target_type": "user",
                    "description": "只能发给用户的专属礼物"
                },
                "3": {
                    "name": "免费礼物",
                    "support_exclusive_tab": False,
                    "support_backpack": True,
                    "target_param": "user_id",
                    "target_type": "user",
                    "description": "可以发放到背包的免费礼物"
                },
                "4": {
                    "name": "白给礼物",
                    "support_exclusive_tab": False,
                    "support_backpack": True,
                    "target_param": "user_id",
                    "target_type": "user",
                    "description": "可以发放到背包的白给礼物"
                },
                "7": {
                    "name": "直播间专属礼物",
                    "support_exclusive_tab": True,
                    "support_backpack": False,
                    "target_param": "room_id",
                    "target_type": "room",
                    "description": "只能发给直播间的专属礼物"
                },
                "8": {
                    "name": "随机礼物",
                    "support_exclusive_tab": True,
                    "support_backpack": False,
                    "target_param": "user_id",
                    "target_type": "user_or_room",
                    "description": "可以发给用户或直播间的随机礼物"
                }
            }
        }
    
    @classmethod
    def get_gift_types(cls, business_code: str = "ear_test") -> Dict[str, Dict[str, Any]]:
        """
        获取礼物类型字典
        
        Args:
            business_code: 业务代码
            
        Returns:
            礼物类型字典
        """
        config = cls.load_config(business_code)
        return config.get("gift_types", {})
    
    @classmethod
    def get_gift_type_info(cls, prefix: str, business_code: str = "ear_test") -> Dict[str, Any]:
        """
        获取指定前缀的礼物类型信息
        
        Args:
            prefix: 礼物ID前缀（如"2", "7", "8"）
            business_code: 业务代码
            
        Returns:
            礼物类型信息字典
        """
        gift_types = cls.get_gift_types(business_code)
        return gift_types.get(str(prefix), {})
    
    @classmethod
    def get_gift_types_list(cls, business_code: str = "ear_test") -> List[Dict[str, Any]]:
        """
        获取礼物类型列表（用于API响应）
        
        Args:
            business_code: 业务代码
            
        Returns:
            礼物类型列表
        """
        gift_types = cls.get_gift_types(business_code)
        types_list = []
        
        for prefix, config in gift_types.items():
            types_list.append({
                "prefix": prefix,
                "type": config.get("name"),
                "description": config.get("description"),
                "support_exclusive_tab": config.get("support_exclusive_tab", False),
                "support_backpack": config.get("support_backpack", False),
                "target_type": config.get("target_type", "user")
            })
        
        # 按前缀排序
        types_list.sort(key=lambda x: x["prefix"])
        
        return types_list
    
    @classmethod
    def get_issue_type_by_prefix(cls, prefix: str, business_code: str = "ear_test") -> str:
        """
        根据礼物ID前缀获取issue_type
        
        Args:
            prefix: 礼物ID前缀
            business_code: 业务代码
            
        Returns:
            issue_type字符串（user, room, random）
        """
        gift_type_info = cls.get_gift_type_info(prefix, business_code)
        target_type = gift_type_info.get("target_type", "user")
        
        # 映射target_type到issue_type
        if target_type == "room":
            return "room"
        elif target_type == "user_or_room":
            return "random"
        else:
            return "user"
    
    @classmethod
    def reload_config(cls, business_code: str = "ear_test"):
        """
        重新加载配置（支持热更新）
        
        Args:
            business_code: 业务代码
        """
        if business_code in cls._config_cache:
            del cls._config_cache[business_code]
        cls.load_config(business_code)
        logger.info(f"✓ 礼物类型配置已重新加载 (business: {business_code})")
