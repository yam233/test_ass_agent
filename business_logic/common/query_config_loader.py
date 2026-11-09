"""
查询配置加载器
用于加载礼物查询相关的配置（通用词、帮助消息等）
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class QueryConfigLoader:
    """查询配置加载器"""
    
    _config_cache: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def load_config(cls, business_code: str = "ear_test") -> Dict[str, Any]:
        """
        加载查询配置
        
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
                    "query_config.json"
                )
                logger.info(f"✓ 查询配置已加载 (business: {business_code})")
            except Exception as e:
                logger.warning(f"加载查询配置失败 (business: {business_code}): {e}")
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
            "generic_terms": [
                "信息", "礼物信息", "类型", "礼物类型",
                "详情", "礼物详情", "查询", "礼物", "礼品"
            ],
            "help_messages": {
                "no_params": "请提供礼物ID或名称\n\n支持以下查询方式：\n• 按ID查询：检查礼物301的类型\n• 按名称查询：查询礼物猫粮\n• 模糊搜索：查询包含天使的礼物\n\n提示：输入\"列出所有礼物类型\"可查看礼物分类规则",
                "generic_term": "请提供具体的礼物ID或名称\n\n支持以下查询方式：\n• 按ID查询：检查礼物301的类型\n• 按名称查询：查询礼物猫粮\n• 模糊搜索：查询包含天使的礼物\n\n提示：输入\"列出所有礼物类型\"可查看礼物分类规则"
            },
            "examples": {
                "gift_id": 301,
                "gift_name": "猫粮",
                "keyword": "天使"
            },
            "response_icons": {
                "success": "✅",
                "error": "❌",
                "warning": "⚠️",
                "info": "ℹ️"
            }
        }
    
    @classmethod
    def get_generic_terms(cls, business_code: str = "ear_test") -> List[str]:
        """
        获取通用词列表
        
        Args:
            business_code: 业务代码
            
        Returns:
            通用词列表
        """
        config = cls.load_config(business_code)
        return config.get("generic_terms", [])
    
    @classmethod
    def get_help_message(cls, message_type: str, business_code: str = "ear_test") -> str:
        """
        获取帮助消息（支持模板变量替换）
        
        Args:
            message_type: 消息类型（no_params, generic_term）
            business_code: 业务代码
            
        Returns:
            帮助消息字符串
        """
        config = cls.load_config(business_code)
        examples = config.get("examples", {})
        message_template = config.get("help_messages", {}).get(message_type, "")
        
        # 替换占位符
        try:
            return message_template.format(
                example_gift_id=examples.get("gift_id", 301),
                example_gift_name=examples.get("gift_name", "猫粮"),
                example_keyword=examples.get("keyword", "天使")
            )
        except Exception as e:
            logger.warning(f"格式化帮助消息失败: {e}")
            return message_template
    
    @classmethod
    def get_response_icon(cls, icon_type: str, business_code: str = "ear_test") -> str:
        """
        获取响应图标
        
        Args:
            icon_type: 图标类型（success, error, warning, info）
            business_code: 业务代码
            
        Returns:
            图标字符串
        """
        config = cls.load_config(business_code)
        icons = config.get("response_icons", {})
        return icons.get(icon_type, "")
    
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
        logger.info(f"✓ 查询配置已重新加载 (business: {business_code})")
