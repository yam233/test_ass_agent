"""
礼物类型定义和校验逻辑
参考 testopsProject02/core/gift/gift_types.py
"""
from enum import Enum
from typing import Optional, Tuple


class GiftType(Enum):
    """礼物类型枚举"""
    NORMAL = 1          # 常规礼物
    USER_EXCLUSIVE = 2  # 用户专属礼物
    FREE = 3            # 免费礼物
    GIVEAWAY = 4        # 白给礼物
    FAN = 5             # 粉丝礼物
    NOBLE = 6           # 贵族礼物
    ROOM_EXCLUSIVE = 7  # 直播间专属礼物
    RANDOM = 8          # 随机礼物
    POOL = 9            # 奖池礼物


# 礼物类型名称映射
GIFT_TYPE_NAMES = {
    GiftType.NORMAL: "常规礼物",
    GiftType.USER_EXCLUSIVE: "用户专属礼物",
    GiftType.FREE: "免费礼物",
    GiftType.GIVEAWAY: "白给礼物",
    GiftType.FAN: "粉丝礼物",
    GiftType.NOBLE: "贵族礼物",
    GiftType.ROOM_EXCLUSIVE: "直播间专属礼物",
    GiftType.RANDOM: "随机礼物",
    GiftType.POOL: "奖池礼物",
}

# 可以发放到背包的礼物类型（DB插入链路：免费/白给礼物）
BACKPACK_ALLOWED_TYPES = {GiftType.FREE, GiftType.GIVEAWAY}

# 可以发放到专属tab的礼物类型
EXCLUSIVE_TAB_ALLOWED_TYPES = {GiftType.USER_EXCLUSIVE, GiftType.ROOM_EXCLUSIVE, GiftType.RANDOM}


def get_gift_type(gift_id: int) -> Optional[GiftType]:
    """
    根据礼物ID获取礼物类型
    礼物ID的第一位数字代表礼物类型
    """
    try:
        first_digit = int(str(gift_id)[0])
        return GiftType(first_digit)
    except (ValueError, IndexError):
        return None


def get_gift_type_name(gift_type: GiftType) -> str:
    """获取礼物类型名称"""
    return GIFT_TYPE_NAMES.get(gift_type, "未知类型")


def can_add_to_backpack(gift_id: int) -> Tuple[bool, str]:
    """
    校验礼物是否可以发放到背包
    返回: (是否可以, 提示信息)
    """
    gift_type = get_gift_type(gift_id)
    if gift_type is None:
        return False, f"无效的礼物ID: {gift_id}"

    if gift_type in BACKPACK_ALLOWED_TYPES:
        return True, f"✅ {get_gift_type_name(gift_type)}可以发放到背包"
    else:
        return False, f"❌ {get_gift_type_name(gift_type)}不支持发放到背包哦"


def can_add_to_exclusive_tab(gift_id: int, user_id: Optional[int], room_id: Optional[int]) -> Tuple[bool, str]:
    """
    校验礼物是否可以发放到专属tab
    返回: (是否可以, 提示信息)
    """
    gift_type = get_gift_type(gift_id)
    if gift_type is None:
        return False, f"无效的礼物ID: {gift_id}"

    if gift_type not in EXCLUSIVE_TAB_ALLOWED_TYPES:
        return False, f"❌ {get_gift_type_name(gift_type)}不支持发放到专属tab哦"

    # 用户专属礼物：必须有 user_id 且 >0；room_id 必须为空或 0
    if gift_type == GiftType.USER_EXCLUSIVE:
        if not user_id or user_id <= 0:
            return False, "❌ 用户专属礼物只能发给用户，请提供有效 user_id"
        if room_id and room_id > 0:
            return False, "❌ 用户专属礼物无需 room_id，请移除 room_id"
        return True, f"✅ {get_gift_type_name(gift_type)}可以发放到用户专属tab"

    # 直播间专属礼物：必须有 room_id 且 >0；user_id 必须为空或 0
    if gift_type == GiftType.ROOM_EXCLUSIVE:
        if not room_id or room_id <= 0:
            return False, "❌ 直播间专属礼物只能发给直播间，请提供有效 room_id"
        if user_id and user_id > 0:
            return False, "❌ 直播间专属礼物无需 user_id，请移除 user_id"
        return True, f"✅ {get_gift_type_name(gift_type)}可以发放到直播间专属tab"

    # 随机礼物：必须至少提供一个有效目标
    if gift_type == GiftType.RANDOM:
        if (not user_id or user_id <= 0) and (not room_id or room_id <= 0):
            return False, "❌ 随机礼物需要提供有效的 user_id 或 room_id"
        target = "用户" if user_id and user_id > 0 else "直播间"
        return True, f"✅ {get_gift_type_name(gift_type)}可以发放到{target}专属tab"

    return False, "❌ 未知错误"
