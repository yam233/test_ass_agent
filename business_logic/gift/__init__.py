"""
礼物发放模块
"""
from .gift_types import (
    GiftType,
    get_gift_type,
    get_gift_type_name,
    can_add_to_backpack,
    can_add_to_exclusive_tab,
    EXCLUSIVE_TAB_ALLOWED_TYPES,
    BACKPACK_ALLOWED_TYPES
)
from .gift_service import (
    add_to_exclusive_tab,
    add_to_backpack,
    query_gift_records,
    delete_gift_record,
    list_gift_types,
    PERMANENT_DURATION,
    DEFAULT_DURATION_DAYS
)

__all__ = [
    'GiftType',
    'get_gift_type',
    'get_gift_type_name',
    'can_add_to_backpack',
    'can_add_to_exclusive_tab',
    'EXCLUSIVE_TAB_ALLOWED_TYPES',
    'BACKPACK_ALLOWED_TYPES',
    'add_to_exclusive_tab',
    'add_to_backpack',
    'query_gift_records',
    'delete_gift_record',
    'list_gift_types',
    'PERMANENT_DURATION',
    'DEFAULT_DURATION_DAYS'
]
