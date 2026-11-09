"""
奖励配置查询服务
参考 testopsProject02/core/config_check/reward_service.py

查询奖励配置的有效期（duration）和最大有效期（end_time）
数据来源：MongoDB test_rewards 集合
"""
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

from business_logic.common.mongo_db import get_mongo_client, get_mongo_config
from utils.message_formatter import MessageFormatter

logger = logging.getLogger(__name__)
load_dotenv()


def query_reward(reward_id: int, event_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    查询奖励配置（通过reward_id）
    
    Args:
        reward_id: 奖励ID
        event_id: 活动ID（可选）
        
    Returns:
        奖励配置数据，如果不存在返回None
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
        
        query = {"reward_id": reward_id}
        if event_id is not None:
            query["event_id"] = event_id
        result = collection.find_one(query)
        return result
    finally:
        client.close()


def query_reward_by_element_id(element_id: int, event_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    查询奖励配置（通过element_id，可能返回多个）
    
    Args:
        element_id: 礼物ID/外观ID
        event_id: 活动ID（可选）
        
    Returns:
        奖励配置数据列表，如果不存在返回空列表
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
        
        query = {"element_id": element_id}
        if event_id is not None:
            query["event_id"] = event_id
        results = list(collection.find(query))
        return results
    finally:
        client.close()


def query_reward_by_event_id(event_id: int) -> List[Dict[str, Any]]:
    """
    查询奖励配置（通过event_id，可能返回多个）
    
    Args:
        event_id: 活动ID
        
    Returns:
        奖励配置数据列表，如果不存在返回空列表
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
        
        results = list(collection.find({"event_id": event_id}))
        return results
    finally:
        client.close()


def format_expire_time(end_time: Any) -> Tuple[str, bool]:
    """
    格式化过期时间
    
    Args:
        end_time: 过期时间（可能是时间戳或None）
        
    Returns:
        (显示文本, 是否未配置)
    """
    if end_time is None or end_time == 0 or end_time == -1:
        return "未配置", True
    
    try:
        if isinstance(end_time, (int, float)):
            # 判断是秒还是毫秒
            if end_time > 10000000000:
                end_time = end_time / 1000
            dt = datetime.fromtimestamp(end_time)
            return dt.strftime("%Y-%m-%d %H:%M:%S"), False
        return str(end_time), False
    except Exception:
        return str(end_time), False


def format_duration(duration: Any) -> str:
    """
    格式化 duration 显示
    
    Args:
        duration: 有效期（秒）
        
    Returns:
        格式化的有效期字符串
    """
    if duration is None or duration == 0:
        return "未配置"
    
    try:
        duration = int(duration)
        days = duration // 86400
        hours = (duration % 86400) // 3600
        minutes = (duration % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days} 天")
        if hours > 0:
            parts.append(f"{hours} 小时")
        if minutes > 0 and days == 0:  # 只在天数为0时显示分钟
            parts.append(f"{minutes} 分钟")
        
        if parts:
            return f"{duration} 秒 ({' '.join(parts)})"
        return f"{duration} 秒"
    except Exception:
        return str(duration)


def query_reward_config(
    reward_id: Optional[int] = None,
    element_id: Optional[int] = None,
    event_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    查询奖励配置（单个）
    
    Args:
        reward_id: 奖励ID（可选）
        element_id: 礼物ID/外观ID（可选）
        event_id: 活动ID（可选）
        
    Returns:
        查询结果字典，包含success、message、data字段
        
    Note:
        reward_id、element_id、event_id 至少提供一个
    """
    # 参数校验
    if reward_id is None and element_id is None and event_id is None:
        return {
            "success": False,
            "message": MessageFormatter.missing_param_error(
                param_name="查询条件",
                param_description="查询条件（reward_id、element_id 或 event_id）",
                examples=[
                    "查询奖励148001的配置",
                    "查询礼物20478的有效期和最大有效期",
                    "查询活动1480的奖励配置"
                ]
            ),
            "data": None
        }
    
    # 查询奖励配置
    if reward_id is not None:
        # 通过reward_id查询，返回单个结果
        data = query_reward(reward_id, event_id=event_id)
        query_key = f"reward_id: {reward_id}"
        
        # 无结果提示未配置该奖励
        if data is None:
            return {
                "success": False,
                "message": MessageFormatter.not_found_error(
                    resource_type="奖励",
                    resource_id=f"{query_key}",
                    examples=[
                        "查询奖励148001的配置",
                        "查询其他奖励ID"
                    ]
                ),
                "data": None
            }
        
        # 处理单个结果
        rewards_list = [data]
    elif element_id is not None:
        # 通过element_id查询，可能返回多个结果
        rewards_list = query_reward_by_element_id(element_id, event_id=event_id)
        query_key = f"element_id: {element_id}"
        
        # 无结果提示未配置该奖励
        if not rewards_list:
            return {
                "success": False,
                "message": MessageFormatter.not_found_error(
                    resource_type="礼物/外观",
                    resource_id=f"{query_key}",
                    examples=[
                        "查询礼物20478的有效期和最大有效期",
                        "查询外观50811的配置"
                    ]
                ),
                "data": None
            }
    else:
        # 通过event_id查询
        rewards_list = query_reward_by_event_id(event_id) if event_id is not None else []
        query_key = f"event_id: {event_id}"
        if not rewards_list:
            return {
                "success": False,
                "message": MessageFormatter.not_found_error(
                    resource_type="活动",
                    resource_id=f"{query_key}",
                    examples=[
                        "查询活动1480的奖励配置",
                        "查询活动1179的奖励配置"
                    ]
                ),
                "data": None
            }
    
    # 处理多个奖励配置
    result_data_list = []
    lines = []
    
    if reward_id is not None:
        query_info = f"奖励 ID {reward_id}"
    elif element_id is not None:
        query_info = f"礼物/外观 ID {element_id}"
    else:
        query_info = f"活动 ID {event_id}"
    
    # 收集所有奖励配置数据
    for i, data in enumerate(rewards_list, 1):
        found_reward_id = data.get("reward_id")
        found_event_id = data.get("event_id")
        intro = data.get("intro")
        reward_type = data.get("type", "未知")
        found_element_id = data.get("element_id", "无")
        element_num = data.get("element_num", 0)
        duration = data.get("duration", 0)
        end_time = data.get("end_time")
        element_type = data.get("element_type")  # 外观类型字段
        
        # 如果是外观类型（有element_type字段），从test_appearances查询最大有效期
        if element_type is not None and end_time is None:
            try:
                from business_logic.config_check.appearance_service import query_appearance
                appearance_data = query_appearance(found_element_id)
                if appearance_data:
                    end_time = appearance_data.get("expire_time")
            except Exception as e:
                logger.warning(f"查询外观 {found_element_id} 的最大有效期失败: {e}")
        
        # 格式化有效期
        duration_str = format_duration(duration)
        
        # 判断是否配置最大有效期（如果存在end_time，则配置了最大有效期）
        has_max_expire = end_time is not None and end_time != 0 and end_time != -1
        expire_str, no_config = format_expire_time(end_time)
        
        # 构建单个奖励配置数据
        reward_data = {
            "event_id": found_event_id,
            "intro": intro,
            "reward_id": found_reward_id,
            "element_id": found_element_id,
            "element_num": element_num,
            "type": reward_type,
            "element_type": element_type,
            "duration": duration,
            "duration_str": duration_str,
            "end_time": end_time,
            "end_time_str": expire_str,
            "has_max_expire": has_max_expire
        }
        result_data_list.append(reward_data)
    
    # 构建表格格式的消息
    if len(rewards_list) > 1:
        lines.append(f"{query_info}: ✅ 找到 {len(rewards_list)} 条奖励配置")
        lines.append("")
        # 表格标题
        lines.append("| 活动ID | 类型 | ID | 奖励ID | 描述 | 有效期 | 最大有效期 |")
        lines.append("|--------|------|----|----|------|--------|------------|")
        
        # 表格数据行
        for reward_data in result_data_list:
            event_id_val = reward_data['event_id'] or '无'
            element_id_val = reward_data['element_id']
            reward_id_val = reward_data['reward_id']
            intro_val = reward_data['intro'] or '无'
            duration_str = reward_data['duration_str']
            max_expire_str = reward_data['end_time_str']
            
            # 判断类型：有element_type字段的是外观，否则是礼物
            if reward_data['element_type'] is not None:
                item_type = "外观"
            else:
                item_type = "礼物"
            
            lines.append(f"| {event_id_val} | {item_type} | {element_id_val} | {reward_id_val} | {intro_val} | {duration_str} | {max_expire_str} |")
    else:
        # 单个结果也使用表格格式
        reward_data = result_data_list[0]
        lines.append(f"{query_info}: ✅ 已配置")
        lines.append("")
        lines.append("| 活动ID | 类型 | ID | 奖励ID | 描述 | 有效期 | 最大有效期 |")
        lines.append("|--------|------|----|----|------|--------|------------|")
        event_id_val = reward_data['event_id'] or '无'
        intro_val = reward_data['intro'] or '无'
        
        # 判断类型：有element_type字段的是外观，否则是礼物
        if reward_data['element_type'] is not None:
            item_type = "外观"
        else:
            item_type = "礼物"
        
        lines.append(f"| {event_id_val} | {item_type} | {reward_data['element_id']} | {reward_data['reward_id']} | {intro_val} | {reward_data['duration_str']} | {reward_data['end_time_str']} |")
    
    message = "\n".join(lines)
    
    # 如果只有一个结果，返回单个对象；如果有多个结果，返回列表
    if len(result_data_list) == 1:
        return {
            "success": True,
            "message": message,
            "data": result_data_list[0]
        }
    else:
        return {
            "success": True,
            "message": message,
            "data": result_data_list,
            "count": len(result_data_list)
        }


def query_reward_configs_batch(
    reward_ids: Optional[List[int]] = None,
    element_ids: Optional[List[int]] = None,
    event_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    批量查询奖励配置
    
    Args:
        reward_ids: 奖励ID列表
        element_ids: 礼物/外观ID列表
        event_id: 活动ID
        
    Returns:
        查询结果列表，每个元素是一个查询结果字典
    """
    results = []
    reward_ids = reward_ids or []
    element_ids = element_ids or []
    # 优先按 reward_ids / element_ids 批量查询
    if reward_ids:
        for reward_id in reward_ids:
            result = query_reward_config(reward_id=reward_id, event_id=event_id)
            results.append(result)
        return results
    if element_ids:
        for element_id in element_ids:
            result = query_reward_config(element_id=element_id, event_id=event_id)
            results.append(result)
        return results
    # 仅 event_id 批量查询（返回 event_id 对应的全部）
    if event_id is not None:
        result = query_reward_config(event_id=event_id)
        # 兼容单条/列表返回
        if result.get("success") and isinstance(result.get("data"), list):
            for item in result.get("data", []):
                results.append({"success": True, "message": "OK", "data": item})
        else:
            results.append(result)
    return results
