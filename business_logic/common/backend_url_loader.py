"""
后台URL配置加载器
从配置文件加载后台功能URL
"""
import json
import os
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class BackendUrlLoader:
    """后台URL配置加载器"""
    
    _config_cache = {}
    _search_engine = None
    
    @classmethod
    def _get_search_engine(cls):
        """获取搜索引擎实例（单例）"""
        if cls._search_engine is None:
            from business_logic.common.smart_search_engine import SmartSearchEngine
            cls._search_engine = SmartSearchEngine()
        return cls._search_engine
    
    @classmethod
    def load_config(cls, business_code: str = "testops") -> Dict[str, Any]:
        """
        加载后台URL配置
        
        Args:
            business_code: 业务代码
            
        Returns:
            配置字典
        """
        # 检查缓存
        if business_code in cls._config_cache:
            return cls._config_cache[business_code]
        
        try:
            # 配置文件路径
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "config",
                "backend_urls.json"
            )
            
            # 加载配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 缓存配置
            cls._config_cache[business_code] = config
            
            logger.info(f"成功加载后台URL配置，共 {len(config)} 个功能")
            return config
            
        except FileNotFoundError:
            logger.error(f"后台URL配置文件不存在: {config_path}")
            return cls._get_default_config()
        except json.JSONDecodeError as e:
            logger.error(f"后台URL配置文件格式错误: {e}")
            return cls._get_default_config()
        except Exception as e:
            logger.error(f"加载后台URL配置失败: {e}")
            return cls._get_default_config()
    
    @classmethod
    def _get_default_config(cls) -> Dict[str, Any]:
        """
        获取默认配置（fallback）
        
        Returns:
            默认配置字典
        """
        return {
            "default": {
                "name": "默认配置",
                "url": "https://internal.example.invalid",
                "source": "unknown",
                "description": "默认配置",
                "tags": [],
                "category": "其他"
            }
        }
    
    @classmethod
    def search_urls(cls, keyword: str, business_code: str = "testops", limit: int = None) -> List[Dict[str, Any]]:
        """
        搜索后台URL（使用智能搜索引擎）
        
        Args:
            keyword: 搜索关键词
            business_code: 业务代码
            limit: 返回结果数量限制（None表示返回所有）
            
        Returns:
            匹配的URL列表（按相关性排序）
        """
        try:
            # 使用智能搜索引擎
            search_engine = cls._get_search_engine()
            results = search_engine.search(keyword, limit=limit)
            
            logger.info(f"搜索关键词: '{keyword}', 返回 {len(results)} 个结果")
            return results
            
        except Exception as e:
            logger.error(f"智能搜索失败，回退到传统搜索: {e}")
            # 回退到传统搜索方法
            return cls._legacy_search_urls(keyword, business_code, limit)
    
    @classmethod
    def list_all_urls(cls, business_code: str = "testops") -> List[Dict[str, Any]]:
        """
        列出所有后台URL
        
        Args:
            business_code: 业务代码
            
        Returns:
            所有URL列表
        """
        config = cls.load_config(business_code)
        
        results = []
        for key, url_config in config.items():
            results.append(cls._format_result(key, url_config))
        
        # 按分类排序
        results.sort(key=lambda x: (x.get('category', ''), x.get('title', '')))
        
        return results
    
    @classmethod
    def get_url_by_key(cls, key: str, business_code: str = "testops") -> Dict[str, Any]:
        """
        根据key获取URL配置
        
        Args:
            key: 配置key
            business_code: 业务代码
            
        Returns:
            URL配置
        """
        config = cls.load_config(business_code)
        
        if key in config:
            return cls._format_result(key, config[key])
        
        return None
    
    @classmethod
    def _format_result(cls, key: str, url_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化结果
        
        Args:
            key: 配置key
            url_config: URL配置
            
        Returns:
            格式化后的结果
        """
        return {
            "key": key,
            "title": url_config.get('name'),
            "url": url_config.get('url'),
            "source": url_config.get('source'),
            "description": url_config.get('description', ''),
            "category": url_config.get('category', '其他'),
            "tags": url_config.get('tags', [])
        }
    
    @classmethod
    def reload_config(cls, business_code: str = "testops"):
        """
        重新加载配置（清除缓存）
        
        Args:
            business_code: 业务代码
        """
        if business_code in cls._config_cache:
            del cls._config_cache[business_code]
        
        # 重新加载搜索引擎
        if cls._search_engine is not None:
            cls._search_engine.reload()
        
        logger.info(f"已清除后台URL配置缓存: {business_code}")
    
    @classmethod
    def _legacy_search_urls(cls, keyword: str, business_code: str = "testops", limit: int = None) -> List[Dict[str, Any]]:
        """
        传统搜索方法（作为备用）
        
        Args:
            keyword: 搜索关键词
            business_code: 业务代码
            limit: 返回结果数量限制
            
        Returns:
            匹配的URL列表
        """
        config = cls.load_config(business_code)
        
        results = []
        keyword_lower = keyword.lower()
        
        for key, url_config in config.items():
            score = 0
            name = url_config.get('name', '')
            description = url_config.get('description', '')
            tags = url_config.get('tags', [])
            
            # 简单匹配
            if keyword_lower in name.lower():
                score += 100
            
            for tag in tags:
                if keyword_lower in tag.lower():
                    score += 50
                    break
            
            if keyword_lower in description.lower():
                score += 20
            
            if score > 0:
                result = cls._format_result(key, url_config)
                result['relevance_score'] = score
                results.append(result)
        
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        if limit:
            results = results[:limit]
        
        return results
