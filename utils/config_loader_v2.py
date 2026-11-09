"""
配置加载器 V2（增强版）

新增功能：
1. 配置验证（Pydantic）
2. 配置缓存（LRU + TTL）
3. 配置热更新支持
4. 统一配置接口
5. 配置版本管理
6. 错误处理增强
"""
import json
import hashlib
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Type, TypeVar, Callable
from functools import lru_cache
from datetime import datetime
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class ConfigCache:
    """配置缓存管理器"""
    
    def __init__(self, ttl: int = 300):
        """
        初始化缓存
        
        Args:
            ttl: 缓存过期时间（秒），默认 5 分钟
        """
        self.ttl = ttl
        self.cache: Dict[str, tuple] = {}  # {key: (data, expire_time, version)}
        self.file_versions: Dict[str, str] = {}  # {file_path: md5}
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，过期或不存在返回 None
        """
        if key not in self.cache:
            return None
        
        data, expire_time, version = self.cache[key]
        
        # 检查是否过期
        if time.time() > expire_time:
            del self.cache[key]
            return None
        
        return data
    
    def set(self, key: str, data: Any, version: str = ""):
        """
        设置缓存
        
        Args:
            key: 缓存键
            data: 缓存数据
            version: 配置版本
        """
        expire_time = time.time() + self.ttl
        self.cache[key] = (data, expire_time, version)
    
    def invalidate(self, key: str):
        """
        使缓存失效
        
        Args:
            key: 缓存键
        """
        if key in self.cache:
            del self.cache[key]
    
    def clear(self):
        """清空所有缓存"""
        self.cache.clear()
        self.file_versions.clear()
    
    def get_stats(self) -> dict:
        """
        获取缓存统计
        
        Returns:
            缓存统计信息
        """
        total = len(self.cache)
        valid = sum(1 for _, (_, expire_time, _) in self.cache.items() if time.time() <= expire_time)
        expired = total - valid
        
        return {
            "total": total,
            "valid": valid,
            "expired": expired
        }


class ConfigLoaderV2:
    """
    配置加载器 V2（增强版）
    
    特性：
    1. 配置验证 - 使用 Pydantic 验证配置
    2. 配置缓存 - 减少文件读取
    3. 配置热更新 - 检测文件变更
    4. 统一接口 - 简化配置访问
    5. 错误处理 - 详细的错误信息
    
    使用示例：
        # 加载配置
        config = ConfigLoaderV2.load("ear_test", "skills_registry.json")
        
        # 加载并验证配置
        from pydantic import BaseModel
        class SkillConfig(BaseModel):
            skill_name: str
            description: str
        
        config = ConfigLoaderV2.load_and_validate(
            "ear_test", 
            "skills_registry.json",
            SkillConfig
        )
        
        # 清空缓存
        ConfigLoaderV2.clear_cache()
    """
    
    # 全局缓存实例
    _cache = ConfigCache(ttl=300)  # 5 分钟缓存
    
    # 配置变更回调
    _watchers: Dict[str, list] = {}
    
    @classmethod
    def load(
        cls,
        business_code: Optional[str] = None,
        config_name: str = "",
        use_cache: bool = True,
        validate: bool = True
    ) -> Dict[str, Any]:
        """
        加载配置文件
        
        Args:
            business_code: 业务代码，None 表示框架配置
            config_name: 配置文件名
            use_cache: 是否使用缓存
            validate: 是否验证 JSON 格式
            
        Returns:
            配置字典
            
        Raises:
            FileNotFoundError: 配置文件不存在
            json.JSONDecodeError: JSON 格式错误
        """
        # 构造缓存键
        cache_key = f"{business_code or 'framework'}:{config_name}"
        
        # 1. 尝试从缓存获取
        if use_cache:
            cached_data = cls._cache.get(cache_key)
            if cached_data is not None:
                logger.debug(f"配置缓存命中: {cache_key}")
                return cached_data
        
        # 2. 构造文件路径
        file_path = cls._get_config_path(business_code, config_name)
        
        if not file_path.exists():
            logger.warning(f"配置文件不存在: {file_path}")
            return {}
        
        # 3. 读取配置文件
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # 4. 计算文件版本
            version = cls._calculate_file_version(file_path)
            
            # 5. 检测配置变更
            old_version = cls._cache.file_versions.get(str(file_path))
            if old_version and old_version != version:
                logger.info(f"检测到配置变更: {config_name}")
                cls._trigger_watchers(cache_key, config_data)
            
            cls._cache.file_versions[str(file_path)] = version
            
            # 6. 设置缓存
            if use_cache:
                cls._cache.set(cache_key, config_data, version)
            
            logger.debug(f"配置加载成功: {cache_key}")
            return config_data
            
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 格式错误 ({file_path}): {e}")
            raise
        except Exception as e:
            logger.error(f"配置文件加载失败 ({file_path}): {e}")
            raise
    
    @classmethod
    def load_and_validate(
        cls,
        business_code: Optional[str],
        config_name: str,
        model: Type[T],
        use_cache: bool = True
    ) -> T:
        """
        加载并验证配置
        
        Args:
            business_code: 业务代码
            config_name: 配置文件名
            model: Pydantic 模型类
            use_cache: 是否使用缓存
            
        Returns:
            验证后的配置对象
            
        Raises:
            ValidationError: 配置验证失败
        """
        config_data = cls.load(business_code, config_name, use_cache)
        
        try:
            return model(**config_data)
        except ValidationError as e:
            logger.error(f"配置验证失败 ({config_name}): {e}")
            raise
    
    @classmethod
    def load_business_config(cls, business_code: str, config_name: str) -> Dict[str, Any]:
        """
        加载业务配置（兼容旧接口）
        
        Args:
            business_code: 业务代码
            config_name: 配置文件名
            
        Returns:
            配置字典
        """
        return cls.load(business_code, config_name)
    
    @classmethod
    def load_framework_config(cls, config_name: str) -> Dict[str, Any]:
        """
        加载框架配置（兼容旧接口）
        
        Args:
            config_name: 配置文件名
            
        Returns:
            配置字典
        """
        return cls.load(None, config_name)
    
    @classmethod
    def reload(cls, business_code: Optional[str], config_name: str) -> Dict[str, Any]:
        """
        重新加载配置（强制刷新缓存）
        
        Args:
            business_code: 业务代码
            config_name: 配置文件名
            
        Returns:
            配置字典
        """
        cache_key = f"{business_code or 'framework'}:{config_name}"
        cls._cache.invalidate(cache_key)
        return cls.load(business_code, config_name, use_cache=False)
    
    @classmethod
    def watch(cls, business_code: Optional[str], config_name: str, callback: Callable):
        """
        监听配置变更
        
        Args:
            business_code: 业务代码
            config_name: 配置文件名
            callback: 回调函数，接收新配置作为参数
        """
        cache_key = f"{business_code or 'framework'}:{config_name}"
        
        if cache_key not in cls._watchers:
            cls._watchers[cache_key] = []
        
        cls._watchers[cache_key].append(callback)
        logger.info(f"添加配置监听: {cache_key}")
    
    # clear_cache 方法已移除，避免误操作缓存
    
    @classmethod
    def get_cache_stats(cls) -> dict:
        """
        获取缓存统计
        
        Returns:
            缓存统计信息
        """
        return cls._cache.get_stats()
    
    @classmethod
    def _get_config_path(cls, business_code: Optional[str], config_name: str) -> Path:
        """
        获取配置文件路径
        
        Args:
            business_code: 业务代码，None 表示框架配置
            config_name: 配置文件名
            
        Returns:
            配置文件路径
        """
        if business_code:
            # 业务配置
            return Path(f"config/business/{business_code}/{config_name}")
        else:
            # 框架配置
            return Path(f"config/framework/{config_name}")
    
    @classmethod
    def _calculate_file_version(cls, file_path: Path) -> str:
        """
        计算文件版本（MD5）
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件 MD5
        """
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    @classmethod
    def _trigger_watchers(cls, cache_key: str, config_data: Any):
        """
        触发配置变更监听器
        
        Args:
            cache_key: 缓存键
            config_data: 新配置数据
        """
        if cache_key not in cls._watchers:
            return
        
        for callback in cls._watchers[cache_key]:
            try:
                callback(config_data)
            except Exception as e:
                logger.error(f"配置变更回调执行失败: {e}", exc_info=True)


# 便捷函数（兼容旧代码）
def load_business_config(business_code: str, config_name: str) -> Dict[str, Any]:
    """加载业务配置（便捷函数）"""
    return ConfigLoaderV2.load_business_config(business_code, config_name)


def load_framework_config(config_name: str) -> Dict[str, Any]:
    """加载框架配置（便捷函数）"""
    return ConfigLoaderV2.load_framework_config(config_name)


def reload_config(business_code: Optional[str], config_name: str) -> Dict[str, Any]:
    """重新加载配置（便捷函数）"""
    return ConfigLoaderV2.reload(business_code, config_name)


# clear_config_cache 函数已移除，避免误操作缓存
