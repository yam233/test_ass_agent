"""
奖池配置模块
参考 MaoerProject02/core/pool/pool_service.py
"""
from .pool_service import (
    query_pool_config,
    query_gifts_by_name,
    query_gifts_info,
    update_pool_gift_weight_to_max,
    update_pool_gift_weight,
    update_pool_ssr_weight_to_zero
)

__all__ = [
    'query_pool_config',
    'query_gifts_by_name',
    'query_gifts_info',
    'update_pool_gift_weight_to_max',
    'update_pool_gift_weight',
    'update_pool_ssr_weight_to_zero'
]
