"""
环境变量加载工具

功能：
1. 加载 .env 文件
2. 类型转换（字符串、整数、布尔值、JSON）
3. 必填验证
4. 默认值支持
"""
import os
import json
import logging
from typing import Any, Optional, Union
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class EnvLoader:
    """环境变量加载器"""
    
    _loaded = False
    
    @classmethod
    def load(cls, env_file: str = ".env", override: bool = False):
        """
        加载环境变量文件
        
        Args:
            env_file: 环境变量文件路径
            override: 是否覆盖已存在的环境变量
        """
        if cls._loaded and not override:
            logger.debug("环境变量已加载，跳过")
            return
        
        env_path = Path(env_file)
        if not env_path.exists():
            logger.warning(f"环境变量文件不存在: {env_file}")
            logger.info("提示: 数据库配置已迁移到 config/framework/database_config.json")
            return
        
        load_dotenv(env_path, override=override)
        cls._loaded = True
        logger.info(f"✓ 环境变量已加载: {env_file}")
    
    @staticmethod
    def get(
        key: str, 
        default: Any = None, 
        required: bool = False,
        cast: type = str
    ) -> Any:
        """
        获取环境变量
        
        Args:
            key: 环境变量键
            default: 默认值
            required: 是否必填
            cast: 类型转换（str/int/float/bool/json）
            
        Returns:
            环境变量值
            
        Raises:
            ValueError: 必填环境变量未设置
        """
        value = os.getenv(key)
        
        # 检查必填
        if required and value is None:
            raise ValueError(
                f"必填环境变量未设置: {key}\n"
                f"请在 .env 文件中设置 {key}=your_value"
            )
        
        # 使用默认值
        if value is None:
            return default
        
        # 类型转换
        try:
            if cast == str:
                return value
            elif cast == int:
                return int(value)
            elif cast == float:
                return float(value)
            elif cast == bool:
                return value.lower() in ('true', 'yes', '1', 'on')
            elif cast == dict or cast == list:
                return json.loads(value)
            else:
                return value
        except Exception as e:
            logger.error(f"环境变量类型转换失败 ({key}): {e}")
            return default
    
    @staticmethod
    def get_str(key: str, default: str = "", required: bool = False) -> str:
        """获取字符串环境变量"""
        return EnvLoader.get(key, default, required, str)
    
    @staticmethod
    def get_int(key: str, default: int = 0, required: bool = False) -> int:
        """获取整数环境变量"""
        return EnvLoader.get(key, default, required, int)
    
    @staticmethod
    def get_float(key: str, default: float = 0.0, required: bool = False) -> float:
        """获取浮点数环境变量"""
        return EnvLoader.get(key, default, required, float)
    
    @staticmethod
    def get_bool(key: str, default: bool = False, required: bool = False) -> bool:
        """获取布尔值环境变量"""
        return EnvLoader.get(key, default, required, bool)
    
    @staticmethod
    def get_json(key: str, default: Any = None, required: bool = False) -> Any:
        """获取 JSON 环境变量"""
        return EnvLoader.get(key, default, required, dict)


# 自动加载环境变量
EnvLoader.load()


# 便捷函数
def get_env(key: str, default: Any = None, required: bool = False, cast: type = str) -> Any:
    """获取环境变量（便捷函数）"""
    return EnvLoader.get(key, default, required, cast)


def get_env_str(key: str, default: str = "", required: bool = False) -> str:
    """获取字符串环境变量（便捷函数）"""
    return EnvLoader.get_str(key, default, required)


def get_env_int(key: str, default: int = 0, required: bool = False) -> int:
    """获取整数环境变量（便捷函数）"""
    return EnvLoader.get_int(key, default, required)


def get_env_bool(key: str, default: bool = False, required: bool = False) -> bool:
    """获取布尔值环境变量（便捷函数）"""
    return EnvLoader.get_bool(key, default, required)
