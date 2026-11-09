"""
礼物发放服务
参考 MaoerProject02/core/gift/gift_service.py

插入规则：
1. create_time、modified_time、start_time 取当前时间戳
2. 默认有效期7天，永久则 end_time 为当前时间+1000天
3. delete_time、element_sort、more、source、batch_id 默认为0
4. custom_id 取 gift_id
5. 用户专属礼物：custom_type = 3，element_id = user_id
6. 直播间专属礼物：custom_type = 2，element_id = room_id
"""
import time
import logging
from typing import Optional
from datetime import datetime

from business_logic.common import (
    execute_insert,
    execute_query,
    execute_delete,
    check_user_exists,
    check_gift_exists,
    check_room_exists,
    insert_user_item,
    delete_user_item_by_id
)
from .gift_types import (
    get_gift_type,
    get_gift_type_name,
    GiftType,
    EXCLUSIVE_TAB_ALLOWED_TYPES,
    BACKPACK_ALLOWED_TYPES
)

logger = logging.getLogger(__name__)

# 有效期常量
DEFAULT_DURATION_DAYS = 7  # 默认有效期7天
PERMANENT_DURATION = -1    # 永久有效期标识


def format_timestamp(timestamp: int) -> str:
    """
    将时间戳转换为可读的日期时间格式
    
    Args:
        timestamp: Unix时间戳（秒）
        
    Returns:
        格式化的日期时间字符串，例如：2026-02-20 20:30:45
    """
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return str(timestamp)


def add_to_exclusive_tab(
    gift_id: int,
    user_id: Optional[int] = None,
    room_id: Optional[int] = None,
    duration_days: int = DEFAULT_DURATION_DAYS
) -> dict:
    """发放礼物到专属tab (live_custom表)"""
    # 步骤1: 校验礼物ID是否存在（MongoDB）
    try:
        if not check_gift_exists(gift_id):
            return {"success": False, "message": f"❌ 该礼物不存在，请提供正确的礼物id: {gift_id}"}
    except Exception as e:
        logger.error(f"校验礼物ID失败: gift_id={gift_id}, error={e}", exc_info=True)
        return {"success": False, "message": "❌ 礼物校验失败，请稍后重试"}

    # 步骤2: 判断礼物类型
    gift_type = get_gift_type(gift_id)
    if gift_type is None:
        return {"success": False, "message": f"❌ 无效的礼物ID: {gift_id}"}

    # 步骤3: 判断礼物是否为专属礼物/随机礼物
    if gift_type not in EXCLUSIVE_TAB_ALLOWED_TYPES:
        gift_type_name = get_gift_type_name(gift_type)
        
        return {
            "success": False, 
            "message": (
                f"❌ 礼物 {gift_id} 是{gift_type_name}，不支持发放到专属tab\n\n"
                f"💡 提示：只有以下类型的礼物可以发放到专属tab：\n"
                f"  • 2开头 - 用户专属礼物\n"
                f"  • 7开头 - 直播间专属礼物\n"
                f"  • 8开头 - 随机礼物"
            )
        }

    # 步骤4: 根据礼物类型和提供的参数进行校验
    if gift_type == GiftType.USER_EXCLUSIVE:
        if not user_id or user_id <= 0:
            return {"success": False, "message": "❌ 用户专属礼物需要提供有效的 user_id"}
        if room_id and room_id > 0:
            return {"success": False, "message": "❌ 用户专属礼物只能发给用户，请移除 room_id"}
        try:
            if not check_user_exists(user_id):
                return {"success": False, "message": f"❌ 该用户不存在，请提供正确的用户id: {user_id}"}
        except Exception as e:
            logger.error(f"校验用户ID失败: user_id={user_id}, error={e}", exc_info=True)
            return {"success": False, "message": "❌ 用户校验失败，请稍后重试"}

    elif gift_type == GiftType.ROOM_EXCLUSIVE:
        if not room_id or room_id <= 0:
            return {"success": False, "message": "❌ 直播间专属礼物需要提供有效的 room_id"}
        if user_id and user_id > 0:
            return {"success": False, "message": "❌ 直播间专属礼物只能发给直播间，请移除 user_id"}
        try:
            if not check_room_exists(room_id):
                return {"success": False, "message": f"❌ 该直播间不存在，请提供正确的直播间id: {room_id}"}
        except Exception as e:
            logger.error(f"校验直播间ID失败: room_id={room_id}, error={e}", exc_info=True)
            return {"success": False, "message": "❌ 直播间校验失败，请稍后重试"}

    elif gift_type == GiftType.RANDOM:
        if (not user_id or user_id <= 0) and (not room_id or room_id <= 0):
            return {"success": False, "message": "❌ 随机礼物需要提供有效的 user_id 或 room_id"}
        if user_id and user_id > 0:
            try:
                if not check_user_exists(user_id):
                    return {"success": False, "message": f"❌ 该用户不存在，请提供正确的用户id: {user_id}"}
            except Exception as e:
                logger.error(f"校验用户ID失败: user_id={user_id}, error={e}", exc_info=True)
                return {"success": False, "message": "❌ 用户校验失败，请稍后重试"}
        if room_id and room_id > 0:
            try:
                if not check_room_exists(room_id):
                    return {"success": False, "message": f"❌ 该直播间不存在，请提供正确的直播间id: {room_id}"}
            except Exception as e:
                logger.error(f"校验直播间ID失败: room_id={room_id}, error={e}", exc_info=True)
                return {"success": False, "message": "❌ 直播间校验失败，请稍后重试"}

    # 所有校验通过，继续执行发放流程
    current_time = int(time.time())
    if duration_days == PERMANENT_DURATION:
        end_time = current_time + (1000 * 24 * 60 * 60)
        duration_desc = "永久（1000天）"
    else:
        end_time = current_time + (duration_days * 24 * 60 * 60)
        duration_desc = f"{duration_days}天"

    if gift_type == GiftType.USER_EXCLUSIVE:
        element_id = user_id
        custom_type = 3
        room_id_value = 0
    elif gift_type == GiftType.ROOM_EXCLUSIVE:
        element_id = room_id
        custom_type = 2
        room_id_value = room_id
    elif gift_type == GiftType.RANDOM:
        if user_id:
            element_id = user_id
            custom_type = 3
            room_id_value = 0
        else:
            element_id = room_id
            custom_type = 2
            room_id_value = room_id
    else:
        return {"success": False, "message": "未知礼物类型"}

    sql = """
    INSERT INTO live_custom
    (create_time, modified_time, delete_time, custom_type, custom_id, element_id, element_sort, start_time, end_time, more, source, batch_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        current_time, current_time, 0, custom_type, gift_id, element_id, 0,
        current_time, end_time, 0, 0, 0
    )
    try:
        insert_id = execute_insert(sql, params, db_type="live")
        target = f"用户 {element_id}" if custom_type == 3 else f"直播间 {element_id}"
        
        # 格式化时间
        start_time_str = format_timestamp(current_time)
        end_time_str = format_timestamp(end_time)
        
        return {
            "success": True,
            "message": (
                f"✅ 成功发放到专属tab\n"
                f"发放ID：{insert_id}\n"
                f"{target}\n"
                f"礼物ID：{gift_id}\n"
                f"有效期：{duration_desc}\n"
                f"开始时间：{start_time_str}\n"
                f"结束时间：{end_time_str}"
            ),
            "data": {
                "id": insert_id,
                "element_id": element_id,
                "room_id": room_id_value,
                "gift_id": gift_id,
                "custom_type": custom_type,
                "start_time": current_time,
                "end_time": end_time,
                "duration": duration_desc,
                "start_time_str": start_time_str,
                "end_time_str": end_time_str
            }
        }
    except Exception as e:
        logger.error(f"数据库插入失败: {e}", exc_info=True)
        return {"success": False, "message": "❌ 发放失败：数据库写入异常，请稍后重试"}


def query_gift_records(element_id: int, custom_type: int = None) -> list:
    """查询礼物记录"""
    if custom_type:
        sql = "SELECT * FROM live_custom WHERE element_id = %s AND custom_type = %s AND delete_time = 0"
        params = (element_id, custom_type)
    else:
        sql = "SELECT * FROM live_custom WHERE element_id = %s AND delete_time = 0"
        params = (element_id,)
    return execute_query(sql, params, db_type="live")


def add_to_backpack(
    gift_id: int,
    user_id: int,
    num: int = 1,
    duration_days: int = DEFAULT_DURATION_DAYS,
    room_id: Optional[int] = None
) -> dict:
    """发放礼物到背包 (MongoDB test_user_items集合)"""
    try:
        if not check_gift_exists(gift_id):
            return {"success": False, "message": f"❌ 该礼物不存在，请提供正确的礼物id: {gift_id}"}
    except Exception as e:
        logger.error(f"校验礼物ID失败: gift_id={gift_id}, error={e}", exc_info=True)
        return {"success": False, "message": "❌ 礼物校验失败，请稍后重试"}

    gift_type = get_gift_type(gift_id)
    if gift_type is None:
        return {"success": False, "message": f"❌ 无效的礼物ID: {gift_id}"}
    if gift_type not in BACKPACK_ALLOWED_TYPES:
        gift_type_name = get_gift_type_name(gift_type)
        
        return {
            "success": False, 
            "message": (
                f"❌ 礼物 {gift_id} 是{gift_type_name}，不支持发放到背包\n\n"
                f"💡 提示：只有以下类型的礼物可以发放到背包：\n"
                f"  • 3开头 - 免费礼物\n"
                f"  • 4开头 - 白给礼物"
            )
        }
    if not user_id or user_id <= 0:
        return {"success": False, "message": "❌ 发放背包礼物需要提供有效的 user_id"}
    if room_id and room_id > 0:
        return {"success": False, "message": "❌ 暂不支持发放背包礼物到直播间"}
    try:
        if not check_user_exists(user_id):
            return {"success": False, "message": f"❌ 该用户不存在，请提供正确的用户id: {user_id}"}
    except Exception as e:
        logger.error(f"校验用户ID失败: user_id={user_id}, error={e}", exc_info=True)
        return {"success": False, "message": "❌ 用户校验失败，请稍后重试"}

    current_time = int(time.time())
    if duration_days == PERMANENT_DURATION:
        end_time = current_time + (1000 * 24 * 60 * 60)
        duration_desc = "永久（1000天）"
    else:
        end_time = current_time + (duration_days * 24 * 60 * 60)
        duration_desc = f"{duration_days}天"

    try:
        gift_type_value = gift_type.value
        item_id = insert_user_item(
            user_id=user_id, gift_id=gift_id, num=num,
            start_time=current_time, end_time=end_time, gift_type=gift_type_value
        )
        
        # 格式化时间
        start_time_str = format_timestamp(current_time)
        end_time_str = format_timestamp(end_time)
        
        return {
            "success": True,
            "message": (
                f"✅ 成功发放到背包\n"
                f"发放ID：{item_id}\n"
                f"用户：{user_id}\n"
                f"礼物ID：{gift_id}\n"
                f"数量：{num}\n"
                f"有效期：{duration_desc}\n"
                f"开始时间：{start_time_str}\n"
                f"结束时间：{end_time_str}"
            ),
            "data": {
                "_id": item_id, "user_id": user_id, "gift_id": gift_id, "num": num,
                "start_time": current_time, "end_time": end_time, "duration": duration_desc,
                "start_time_str": start_time_str, "end_time_str": end_time_str
            }
        }
    except Exception as e:
        logger.error(f"MongoDB插入失败: {e}", exc_info=True)
        return {"success": False, "message": "❌ 发放失败：数据写入异常，请稍后重试"}


def delete_gift_record(record_id: int) -> dict:
    """删除专属礼物记录（已下线）"""
    logger.warning("调用已下线接口 delete_gift_record: record_id=%s", record_id)
    return {
        "success": False,
        "message": "❌ delete_gift_record 已下线，禁止删除 live_custom 记录。",
        "data": {
            "deprecated": True,
            "disabled_reason": "delete_live_custom_disabled",
            "record_id": record_id
        }
    }


def delete_backpack_item(item_id: str) -> dict:
    """删除背包礼物记录（已下线）"""
    logger.warning("调用已下线接口 delete_backpack_item: item_id=%s", item_id)
    return {
        "success": False,
        "message": "❌ delete_backpack_item 已下线，禁止删除背包记录。",
        "data": {
            "deprecated": True,
            "disabled_reason": "delete_backpack_item_disabled",
            "item_id": item_id
        }
    }


def check_gift_type(gift_id: int) -> dict:
    """
    校验礼物类型
    
    Args:
        gift_id: 礼物ID
        
    Returns:
        礼物类型信息
    """
    try:
        # 检查礼物是否存在
        if not check_gift_exists(gift_id):
            return {
                "success": False,
                "message": f"礼物ID {gift_id} 不存在"
            }
        
        # 获取礼物类型
        gift_type = get_gift_type(gift_id)
        if gift_type is None:
            return {
                "success": False,
                "message": f"无效的礼物ID: {gift_id}"
            }
        
        gift_type_name = get_gift_type_name(gift_type)
        
        return {
            "success": True,
            "data": {
                "gift_id": gift_id,
                "gift_type": gift_type_name,
                "gift_type_code": gift_type.value,
                "is_valid": True
            },
            "message": "校验成功"
        }
        
    except Exception as e:
        logger.error(f"校验礼物类型失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": "校验失败，请稍后重试"
        }


def list_gift_types() -> dict:
    """
    列出所有礼物类型规则
    
    Returns:
        所有礼物类型的配置信息
    """
    try:
        from agent_core.helpers.gift_type_manager import gift_type_manager
        
        all_types = gift_type_manager.get_all_gift_types()
        
        # 格式化输出
        types_list = []
        message_lines = ["✅ 礼物类型规则清单\n"]
        
        for prefix, rule in sorted(all_types.items()):
            types_list.append({
                "prefix": prefix,
                "name": rule["name"],
                "support_exclusive_tab": rule["support_exclusive_tab"],
                "support_backpack": rule["support_backpack"],
                "target_param": rule["target_param"],
                "target_type": rule["target_type"],
                "description": f"{prefix}开头 - {rule['name']}"
            })
            
            # 构建友好的消息
            name = rule["name"]
            features = []
            if rule["support_exclusive_tab"]:
                features.append("支持专属tab")
            if rule["support_backpack"]:
                features.append("支持背包")
            
            feature_str = "、".join(features) if features else "仅常规发放"
            message_lines.append(f"• {prefix}开头 - {name}（{feature_str}）")
        
        message_lines.append(f"\n📊 共 {len(types_list)} 种礼物类型")
        
        return {
            "success": True,
            "data": {},  # 不返回原始数据，避免重复显示
            "message": "\n".join(message_lines)
        }
        
    except Exception as e:
        logger.error(f"列出礼物类型失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 列出礼物类型失败: {str(e)}"
        }
