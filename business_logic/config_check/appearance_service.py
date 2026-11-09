"""
外观资源查询服务
参考 MaoerProject02/core/config_check/appearance_service.py

查询外观资源是否已配置，以及最大有效期设置
数据来源：
- 有效期：MongoDB test_rewards 集合的 duration 字段
- 最大有效期：Grafana 外观资源状态后台的有效期至字段
"""
import os
import logging
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

from business_logic.common.mongo_db import get_mongo_client, get_mongo_config
from utils.message_formatter import MessageFormatter

logger = logging.getLogger(__name__)
load_dotenv()

# 外观类型映射
APPEARANCE_TYPES = {
    1: "座驾",
    2: "头像框",
    3: "名片框",
    4: "气泡框",
    5: "称号",
    6: "挂件",
    7: "进场通知",
    8: "红包封面",
    9: "身份铭牌",
    11: "气泡框字色",
}


def query_appearance_max_validity_from_grafana(appearance_id: int) -> Optional[Dict[str, Any]]:
    """
    从 Grafana 外观资源状态后台查询最大有效期
    
    Args:
        appearance_id: 外观ID
        
    Returns:
        包含最大有效期信息的字典，如果查询失败返回None
    """
    try:
        # Grafana API endpoint (需要根据实际情况配置)
        # 这里使用 MongoDB 的 test_appearances 作为替代
        # 实际应该调用 Grafana API
        client = get_mongo_client()
        try:
            from business_logic.common.mongo_db import get_mongo_collections
            
            config = get_mongo_config()
            db_name = config.get("database", "fm")
            db = client[db_name]
            
            collections = get_mongo_collections()
            appearance_collection = collections.get('appearances', 'test_appearances')
            collection = db[appearance_collection]
            
            result = collection.find_one({"id": appearance_id})
            if result and result.get("expire_time"):
                expire_time = result.get("expire_time")
                # 检查是否为永久（None, 0, -1 或非常大的值）
                if expire_time and expire_time > 0 and expire_time < 9999999999:
                    return {
                        "expire_time": expire_time,
                        "has_config": True
                    }
            return None
        finally:
            client.close()
    except Exception as e:
        logger.warning(f"从 Grafana 查询外观 {appearance_id} 的最大有效期失败: {e}")
        return None


def query_appearance(appearance_id: int) -> Optional[Dict[str, Any]]:
    """
    查询外观配置
    
    Args:
        appearance_id: 外观ID
        
    Returns:
        外观配置数据，如果不存在返回None
    """
    client = get_mongo_client()
    try:
        from business_logic.common.mongo_db import get_mongo_collections
        
        config = get_mongo_config()
        db_name = config.get("database", "fm")
        db = client[db_name]
        
        # 从配置文件获取外观集合名称
        collections = get_mongo_collections()
        appearance_collection = collections.get('appearances', 'test_appearances')
        collection = db[appearance_collection]
        
        result = collection.find_one({"id": appearance_id})
        return result
    finally:
        client.close()


def query_reward_duration(element_id: int) -> Optional[int]:
    """
    从 test_rewards 集合查询有效期
    
    Args:
        element_id: 元素ID（外观ID）
        
    Returns:
        有效期（秒），如果不存在返回None
    """
    client = get_mongo_client()
    try:
        from business_logic.common.mongo_db import get_mongo_collections
        
        config = get_mongo_config()
        db_name = config.get("database", "fm")
        db = client[db_name]
        
        # 从配置文件获取奖励集合名称
        collections = get_mongo_collections()
        reward_collection = collections.get('rewards', 'test_rewards')
        collection = db[reward_collection]
        result = collection.find_one({"element_id": element_id})
        
        if result:
            return result.get("duration")
        return None
    finally:
        client.close()


def format_expire_time(expire_time: Any) -> Tuple[str, bool]:
    """
    格式化过期时间
    
    Args:
        expire_time: 过期时间（可能是时间戳或None）
        
    Returns:
        (显示文本, 是否永久)
    """
    if expire_time is None or expire_time == 0 or expire_time == -1:
        return "永久", True
    
    # 时间戳转换
    try:
        if isinstance(expire_time, (int, float)):
            # 判断是秒还是毫秒
            if expire_time > 10000000000:
                expire_time = expire_time / 1000
            dt = datetime.fromtimestamp(expire_time)
            return dt.strftime("%Y-%m-%d %H:%M:%S"), False
        return str(expire_time), False
    except Exception:
        return str(expire_time), False


def query_appearance_config(appearance_id: int) -> Dict[str, Any]:
    """
    查询外观资源配置（单个）
    
    需求：
    1. 外观有效期：从 test_rewards 的 duration 字段（传参 element_id）
    2. 外观最大有效期：从 test_appearances 的 expire_time 字段（过期时间），查不到返回"未配置"
    
    Args:
        appearance_id: 外观ID
        
    Returns:
        查询结果字典，包含success、message、data字段
    """
    # 查询外观配置（从 test_appearances）
    appearance_data = query_appearance(appearance_id)
    
    # 查询有效期（从 test_rewards 集合，传参 element_id）
    duration_seconds = query_reward_duration(appearance_id)
    
    # 如果两个都没查到，提示未配置
    if appearance_data is None and duration_seconds is None:
        return {
            "success": False,
            "message": MessageFormatter.not_found_error(
                resource_type="外观",
                resource_id=appearance_id,
                examples=[
                    "查询外观50811的有效期和最大有效期",
                    "查询外观40736的配置",
                    "查询外观10281的有效期"
                ]
            ),
            "data": None
        }
    
    # 获取外观基本信息
    app_type = appearance_data.get("type", 0) if appearance_data else 0
    type_name = APPEARANCE_TYPES.get(app_type, f"未知类型({app_type})")
    name = appearance_data.get("name", "未知") if appearance_data else "未知"
    
    # 获取最大有效期（从 test_appearances 的 expire_time，即过期时间）
    expire_time = appearance_data.get("expire_time") if appearance_data else None
    
    # 判断最大有效期是否配置
    # 如果 expire_time 为 None、0、-1 或不存在，则认为未配置
    has_max_expire = False
    expire_str = "未配置"
    
    if expire_time is not None and expire_time != 0 and expire_time != -1:
        # 有配置最大有效期
        has_max_expire = True
        try:
            # 转换时间戳为日期时间
            if expire_time > 10000000000:
                expire_time_sec = expire_time / 1000
            else:
                expire_time_sec = expire_time
            dt = datetime.fromtimestamp(expire_time_sec)
            expire_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            expire_str = str(expire_time)
    
    # 格式化有效期（从 test_rewards 的 duration）
    validity_str = "未配置"
    validity_days = None
    if duration_seconds:
        validity_days = int(duration_seconds / 86400)
        if validity_days > 0:
            validity_str = f"{validity_days}天"
        else:
            hours = int(duration_seconds / 3600)
            if hours > 0:
                validity_str = f"{hours}小时"
            else:
                minutes = int(duration_seconds / 60)
                validity_str = f"{minutes}分钟"
    
    # 构建返回数据
    result_data = {
        "appearance_id": appearance_id,
        "type": app_type,
        "type_name": type_name,
        "name": name,
        "duration_seconds": duration_seconds,
        "validity_days": validity_days,
        "validity_str": validity_str,
        "expire_time": expire_time,
        "expire_time_str": expire_str,
        "has_max_expire": has_max_expire
    }
    
    # 构建表格格式的消息
    message = f"外观 ID {appearance_id}: ✅ 已配置\n\n"
    message += "| 外观ID | 类型 | 名称 | 有效期 | 最大有效期 |\n"
    message += "|--------|------|------|--------|------------|\n"
    message += f"| {appearance_id} | {type_name} | {name} | {validity_str} | {expire_str} |"
    
    return {
        "success": True,
        "message": message,
        "data": result_data
    }


def query_appearance_configs_batch(appearance_ids: List[int]) -> List[Dict[str, Any]]:
    """
    批量查询外观资源配置
    
    Args:
        appearance_ids: 外观ID列表
        
    Returns:
        查询结果列表，每个元素是一个查询结果字典
    """
    results = []
    for appearance_id in appearance_ids:
        result = query_appearance_config(appearance_id)
        results.append(result)
    return results
