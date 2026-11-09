"""
钻石发放服务
已下线：禁止直连数据库修改钻石余额
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def top_up_diamond(
    user_id: Optional[int] = None,
    phone: Optional[str] = None,
    diamond_100w_units: int = 1
) -> dict:
    """
    发放钻石（已下线）

    为避免误操作数据库，本函数已禁用。
    充值流程请使用测试工具平台实现。
    """
    logger.warning(
        "调用已下线接口 top_up_diamond: user_id=%s phone=%s units=%s",
        user_id,
        phone,
        diamond_100w_units,
    )
    return {
        "success": False,
        "message": "❌ 该接口已下线，禁止直连数据库充值钻石。请使用测试工具平台充值流程。",
        "data": {
            "deprecated": True,
            "disabled_reason": "direct_db_topup_disabled",
        },
    }


def top_up_diamond_by_phone(phone: str, diamond_100w_units: int = 1) -> dict:
    """
    通过手机号发放钻石（已下线）
    """
    return top_up_diamond(phone=phone, diamond_100w_units=diamond_100w_units)
