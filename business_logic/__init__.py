"""Business logic package with lazy exports."""

_EXPORTS = {
    "query_user_info": ("business_logic.user", "query_user_info"),
    "query_verify_code": ("business_logic.user", "query_verify_code"),
    "test_connection": ("business_logic.common.db", "test_connection"),
    "add_to_exclusive_tab": ("business_logic.gift", "add_to_exclusive_tab"),
    "add_to_backpack": ("business_logic.gift", "add_to_backpack"),
    "query_gift_records": ("business_logic.gift", "query_gift_records"),
    "delete_gift_record": ("business_logic.gift", "delete_gift_record"),
    "get_gift_type": ("business_logic.gift", "get_gift_type"),
    "get_gift_type_name": ("business_logic.gift", "get_gift_type_name"),
    "can_add_to_backpack": ("business_logic.gift", "can_add_to_backpack"),
    "can_add_to_exclusive_tab": ("business_logic.gift", "can_add_to_exclusive_tab"),
    "GiftType": ("business_logic.gift", "GiftType"),
    "PERMANENT_DURATION": ("business_logic.gift", "PERMANENT_DURATION"),
    "DEFAULT_DURATION_DAYS": ("business_logic.gift", "DEFAULT_DURATION_DAYS"),
    "query_pool_config": ("business_logic.pool", "query_pool_config"),
    "query_gifts_by_name": ("business_logic.pool", "query_gifts_by_name"),
    "query_gifts_info": ("business_logic.pool", "query_gifts_info"),
    "update_pool_gift_weight_to_max": ("business_logic.pool", "update_pool_gift_weight_to_max"),
    "update_pool_gift_weight": ("business_logic.pool", "update_pool_gift_weight"),
    "update_pool_ssr_weight_to_zero": ("business_logic.pool", "update_pool_ssr_weight_to_zero"),
    "query_appearance_config": ("business_logic.config_check", "query_appearance_config"),
    "query_appearance_configs_batch": ("business_logic.config_check", "query_appearance_configs_batch"),
    "query_reward_config": ("business_logic.config_check", "query_reward_config"),
    "query_reward_configs_batch": ("business_logic.config_check", "query_reward_configs_batch"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'business_logic' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module
    module = import_module(module_name)
    return getattr(module, attr_name)
