"""Common business helpers with lazy exports."""

_EXPORTS = {
    "get_connection": ("business_logic.common.db", "get_connection"),
    "execute_query": ("business_logic.common.db", "execute_query"),
    "execute_insert": ("business_logic.common.db", "execute_insert"),
    "execute_delete": ("business_logic.common.db", "execute_delete"),
    "check_user_exists": ("business_logic.common.db", "check_user_exists"),
    "query_user_info": ("business_logic.common.db", "query_user_info"),
    "test_connection": ("business_logic.common.db", "test_connection"),
    "get_mongo_client": ("business_logic.common.mongo_db", "get_mongo_client"),
    "check_room_exists": ("business_logic.common.mongo_db", "check_room_exists"),
    "query_room_info": ("business_logic.common.mongo_db", "query_room_info"),
    "query_room_by_user_id": ("business_logic.common.mongo_db", "query_room_by_user_id"),
    "check_gift_exists": ("business_logic.common.mongo_db", "check_gift_exists"),
    "query_gift_info": ("business_logic.common.mongo_db", "query_gift_info"),
    "insert_user_item": ("business_logic.common.mongo_db", "insert_user_item"),
    "delete_user_item_by_id": ("business_logic.common.mongo_db", "delete_user_item_by_id"),
    "test_mongo_connection": ("business_logic.common.mongo_db", "test_mongo_connection"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'business_logic.common' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module
    module = import_module(module_name)
    return getattr(module, attr_name)
