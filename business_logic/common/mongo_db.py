"""
MongoDB 连接模块
参考 testopsProject02/core/common/mongo_db.py
用于查询礼物ID和直播间ID是否存在
"""
import json
import os
from typing import Optional
from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import requests
import logging

from agent_core.skills.standard import DatabaseQuerySkill

logger = logging.getLogger(__name__)

# 加载数据库配置文件
_db_config_cache = None


def _env_bool(name: str, default: bool = False) -> bool:
    """从环境变量读取布尔值。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_mongo_proxy_config() -> dict:
    """读取 Mongo HTTP 代理配置。"""
    return {
        "enabled": _env_bool("MONGO_PROXY_ENABLED", False),
        "base_url": os.getenv("MONGO_PROXY_BASE_URL", "").rstrip("/"),
        "api_key": os.getenv("MONGO_PROXY_API_KEY", ""),
        "timeout": int(os.getenv("MONGO_PROXY_TIMEOUT_SECONDS", "8")),
        "fallback_direct": _env_bool("MONGO_PROXY_FALLBACK_DIRECT", True),
    }


def _mongo_proxy_ready() -> bool:
    cfg = _get_mongo_proxy_config()
    return cfg["enabled"] and bool(cfg["base_url"]) and bool(cfg["api_key"])


def _mongo_proxy_strict_only() -> bool:
    """启用代理且关闭回退时，表示严格只走代理。"""
    cfg = _get_mongo_proxy_config()
    return cfg["enabled"] and (not cfg["fallback_direct"])


def _mongo_proxy_headers(api_key: str) -> dict:
    return {
        "X-API-Key": api_key,
        "content-type": "application/json",
    }


def _mongo_proxy_query(collection: str, query: dict) -> list:
    valid, error = DatabaseQuerySkill.validate_mongo_query(query)
    if not valid:
        raise ValueError(error)
    cfg = _get_mongo_proxy_config()
    url = f"{cfg['base_url']}/{collection}/query"
    try:
        resp = requests.post(
            url,
            headers=_mongo_proxy_headers(cfg["api_key"]),
            json=query,
            timeout=cfg["timeout"],
        )
    except requests.RequestException as e:
        raise Exception(f"request_error[{type(e).__name__}] url={url} detail={repr(e)}")
    if not resp.ok:
        raise Exception(
            f"http_{resp.status_code} url={url} body={resp.text[:300]}"
        )
    data = resp.json()
    if isinstance(data, list):
        return data
    raise Exception(f"Mongo proxy query 返回格式异常: {type(data)}")


def _mongo_proxy_insert(collection: str, data: dict) -> str:
    cfg = _get_mongo_proxy_config()
    url = f"{cfg['base_url']}/{collection}/insert"
    try:
        resp = requests.post(
            url,
            headers=_mongo_proxy_headers(cfg["api_key"]),
            json=data,
            timeout=cfg["timeout"],
        )
    except requests.RequestException as e:
        raise Exception(f"request_error[{type(e).__name__}] url={url} detail={repr(e)}")
    if not resp.ok:
        raise Exception(
            f"http_{resp.status_code} url={url} body={resp.text[:300]}"
        )
    payload = resp.json()
    inserted_id = payload.get("id")
    if not inserted_id:
        raise Exception("Mongo proxy insert 响应缺少 id")
    return str(inserted_id)


def _mongo_proxy_delete_by_id(collection: str, obj_id: str) -> bool:
    cfg = _get_mongo_proxy_config()
    url = f"{cfg['base_url']}/{collection}/{obj_id}"
    try:
        resp = requests.delete(
            url,
            headers=_mongo_proxy_headers(cfg["api_key"]),
            timeout=cfg["timeout"],
        )
    except requests.RequestException as e:
        raise Exception(f"request_error[{type(e).__name__}] url={url} detail={repr(e)}")
    if not resp.ok:
        raise Exception(
            f"http_{resp.status_code} url={url} body={resp.text[:300]}"
        )
    payload = resp.json()
    return payload.get("deleted_count", 0) > 0

def _load_db_config() -> dict:
    """加载数据库配置文件"""
    global _db_config_cache
    if _db_config_cache is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'config', 'framework', 'database_config.json'
        )
        with open(config_path, 'r', encoding='utf-8') as f:
            _db_config_cache = json.load(f)
    return _db_config_cache


def get_mongo_config() -> dict:
    """
    获取 MongoDB 配置（从配置文件）
    
    Returns:
        MongoDB 配置字典
    """
    config = _load_db_config()
    mongo_config = config['mongodb']
    
    return {
        "connection_string": mongo_config['connection_string'],
        "host": mongo_config['host'],
        "port": mongo_config['port'],
        "username": mongo_config['username'],
        "password": mongo_config['password'],
        "database": mongo_config['database'],
        "auth_source": mongo_config.get('auth_source', 'admin')
    }


def get_mongo_collections() -> dict:
    """
    获取 MongoDB 集合配置（从配置文件）
    
    Returns:
        集合名称字典
    """
    config = _load_db_config()
    collections = config['mongodb']['collections']
    
    return {
        "gifts": collections.get('gifts', 'test_gifts'),
        "rooms": collections.get('rooms', 'test_rooms'),
        "user_items": collections.get('user_items', 'test_user_items'),
        "appearances": collections.get('appearances', 'test_appearances'),
        "rewards": collections.get('rewards', 'test_rewards'),
        "pool": collections.get('pool', 'test_gift_draw_pool')
    }


def get_mongo_client() -> MongoClient:
    """
    获取 MongoDB 客户端连接
    
    Returns:
        MongoClient 实例
    """
    config = get_mongo_config()
    
    # 如果配置中有 connection_string，优先使用连接字符串
    if config.get("connection_string"):
        return MongoClient(
            config["connection_string"],
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
        )
    
    # 否则使用 host 和 port 参数
    connection_params = {
        "host": config["host"],
        "port": config["port"],
        "serverSelectionTimeoutMS": 30000,
        "connectTimeoutMS": 30000,
        "socketTimeoutMS": 30000,
    }
    
    # 如果需要认证，添加认证参数
    if config.get("username") and config.get("password"):
        connection_params["username"] = config["username"]
        connection_params["password"] = config["password"]
        connection_params["authSource"] = config.get("auth_source", "admin")
    
    return MongoClient(**connection_params)


def check_room_exists(room_id: int) -> bool:
    """
    检查直播间ID是否存在
    查询 MongoDB: fm.test_rooms 集合
    
    Args:
        room_id: 直播间ID
    
    Returns:
        直播间是否存在
    """
    collections = get_mongo_collections()
    if _mongo_proxy_strict_only() and not _mongo_proxy_ready():
        raise Exception("Mongo Proxy 已启用且禁止回退，但代理配置不完整或不可用")
    if _mongo_proxy_ready():
        try:
            docs = _mongo_proxy_query(collections["rooms"], {"room_id": room_id})
            logger.info("check_room_exists 走 Mongo Proxy")
            return len(docs) > 0
        except Exception as e:
            cfg = _get_mongo_proxy_config()
            logger.warning(f"check_room_exists 代理查询失败: {e}")
            if not cfg["fallback_direct"]:
                raise Exception(f"Mongo proxy 查询直播间失败: {str(e)}")

    try:
        client = get_mongo_client()
        config = get_mongo_config()
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["rooms"]]

        result = collection.find_one({"room_id": room_id})
        client.close()
        return result is not None
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接 MongoDB 验证直播间ID {room_id}: {e}")
        raise Exception(f"无法连接 MongoDB 验证直播间ID {room_id}: {str(e)}")
    except Exception as e:
        logger.error(f"查询直播间ID {room_id} 时发生错误: {e}")
        raise Exception(f"查询直播间ID {room_id} 时发生错误: {str(e)}")


def query_room_info(room_id: int) -> Optional[dict]:
    """
    查询直播间信息
    查询 MongoDB: fm.test_rooms 集合
    
    Args:
        room_id: 直播间ID
    
    Returns:
        直播间信息字典，如果不存在则返回 None
    """
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        collections = get_mongo_collections()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["rooms"]]
        
        # 查询直播间信息
        result = collection.find_one({"room_id": room_id})
        client.close()
        
        if result:
            return {
                "room_id": result.get("room_id"),
                "name": result.get("name"),
                "creator_id": result.get("creator_id"),
                "creator_username": result.get("creator_username"),
                "status": result.get("status", {}),
                "statistics": result.get("statistics", {})
            }
        return None
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接 MongoDB 查询直播间ID {room_id}: {e}")
        raise Exception(f"无法连接 MongoDB 查询直播间ID {room_id}: {str(e)}")
    except Exception as e:
        logger.error(f"查询直播间ID {room_id} 时发生错误: {e}")
        raise Exception(f"查询直播间ID {room_id} 时发生错误: {str(e)}")


def query_room_by_user_id(user_id: int) -> Optional[dict]:
    """
    通过用户ID查询直播间信息
    查询 MongoDB: fm.test_rooms 集合
    
    Args:
        user_id: 用户ID
    
    Returns:
        直播间信息字典，如果不存在则返回 None
    """
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        collections = get_mongo_collections()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["rooms"]]
        
        # 查询用户的直播间
        result = collection.find_one({"creator_id": user_id})
        client.close()
        
        if result:
            return {
                "room_id": result.get("room_id"),
                "name": result.get("name"),
                "creator_id": result.get("creator_id"),
                "creator_username": result.get("creator_username"),
                "status": result.get("status", {}),
                "statistics": result.get("statistics", {})
            }
        return None
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接 MongoDB 查询用户 {user_id} 的直播间: {e}")
        return None
    except Exception as e:
        logger.error(f"查询用户 {user_id} 的直播间时发生错误: {e}")
        return None


def check_gift_exists(gift_id: int) -> bool:
    """
    检查礼物ID是否存在
    查询 MongoDB: fm.test_gifts 集合
    
    Args:
        gift_id: 礼物ID
    
    Returns:
        礼物是否存在
    """
    collections = get_mongo_collections()
    if _mongo_proxy_strict_only() and not _mongo_proxy_ready():
        raise Exception("Mongo Proxy 已启用且禁止回退，但代理配置不完整或不可用")
    if _mongo_proxy_ready():
        try:
            docs = _mongo_proxy_query(collections["gifts"], {"gift_id": gift_id})
            logger.info("check_gift_exists 走 Mongo Proxy")
            return len(docs) > 0
        except Exception as e:
            cfg = _get_mongo_proxy_config()
            logger.warning(f"check_gift_exists 代理查询失败: {e}")
            if not cfg["fallback_direct"]:
                raise Exception(f"Mongo proxy 查询礼物失败: {str(e)}")

    try:
        client = get_mongo_client()
        config = get_mongo_config()
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["gifts"]]

        result = collection.find_one({"gift_id": gift_id})
        client.close()
        return result is not None
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接 MongoDB 验证礼物ID {gift_id}: {e}")
        raise Exception(f"无法连接 MongoDB 验证礼物ID {gift_id}: {str(e)}")
    except Exception as e:
        logger.error(f"查询礼物ID {gift_id} 时发生错误: {e}")
        raise Exception(f"查询礼物ID {gift_id} 时发生错误: {str(e)}")


def query_gift_info(gift_id: int = None, gift_ids: list = None, gift_name: str = None, limit: int = 10) -> dict:
    """
    查询礼物信息（支持按ID、批量ID或名称模糊查询）
    查询 MongoDB: fm.test_gifts 集合
    
    Args:
        gift_id: 礼物ID（可选，单个查询）
        gift_ids: 礼物ID列表（可选，批量查询）
        gift_name: 礼物名称（可选，支持模糊查询）
        limit: 最多返回结果数（名称查询时使用）
    
    Returns:
        查询结果字典
    """
    # 从配置文件加载通用词列表
    from business_logic.common.query_config_loader import QueryConfigLoader
    generic_terms = QueryConfigLoader.get_generic_terms()
    
    try:
        config = get_mongo_config()
        collections = get_mongo_collections()
        use_proxy = _mongo_proxy_ready()
        proxy_fallback_direct = _get_mongo_proxy_config()["fallback_direct"]
        if _mongo_proxy_strict_only() and not use_proxy:
            raise Exception("Mongo Proxy 已启用且禁止回退，但代理配置不完整或不可用")
        query_route = "proxy" if use_proxy else "direct"
        collection = None

        if not use_proxy:
            client = get_mongo_client()
            db_name = config.get("database", "fm")
            db = client[db_name]
            collection = db[collections["gifts"]]
        
        # 构建查询条件
        if gift_id is not None:
            # 按ID精确查询（单个）
            if use_proxy:
                try:
                    docs = _mongo_proxy_query(collections["gifts"], {"gift_id": gift_id})
                    logger.info("query_gift_info(single) 走 Mongo Proxy")
                    result = docs[0] if docs else None
                except Exception as e:
                    logger.warning(f"query_gift_info(single) 代理查询失败: {e}")
                    if not proxy_fallback_direct:
                        raise Exception(f"Mongo proxy 查询礼物失败: {str(e)}")
                    query_route = "direct"
                    client = get_mongo_client()
                    db_name = config.get("database", "fm")
                    db = client[db_name]
                    collection = db[collections["gifts"]]
                    result = collection.find_one({"gift_id": gift_id})
                    client.close()
            else:
                result = collection.find_one({"gift_id": gift_id})
                client.close()
            
            if result:
                # 导入礼物类型映射
                from business_logic.gift.gift_types import GiftType, GIFT_TYPE_NAMES
                
                gift_type_value = result.get("type")
                # 将数字类型转换为枚举
                try:
                    gift_type_enum = GiftType(gift_type_value)
                    gift_type_name = GIFT_TYPE_NAMES.get(gift_type_enum, f"未知类型({gift_type_value})")
                except (ValueError, KeyError):
                    gift_type_name = f"未知类型({gift_type_value})"
                
                # 转换特殊类型
                gift_data = {
                    "gift_id": result.get("gift_id"),
                    "name": result.get("name"),
                    "type": gift_type_value,
                    "type_name": gift_type_name,  # 添加类型名称
                    "price": result.get("price"),
                    "point": result.get("point"),
                    "order": result.get("order"),
                    "icon": result.get("icon"),
                    "icon_active": result.get("icon_active"),
                    "intro": result.get("intro"),
                    "comboable": result.get("comboable"),
                    "added_time": result.get("added_time").isoformat() if hasattr(result.get("added_time"), 'isoformat') else str(result.get("added_time"))
                }
                return {
                    "success": True,
                    "message": f"✅ 查询成功\n链路：{query_route}",
                    "data": gift_data,
                    "route": query_route
                }
            else:
                return {
                    "success": False,
                    "message": (
                        f"❌ 未找到礼物ID {gift_id}\n\n"
                        f"💡 可能原因：\n"
                        f"  • 礼物ID不存在或已下架\n"
                        f"  • ID输入错误\n\n"
                        f"📖 建议：\n"
                        f"  • 使用名称搜索：查询礼物猫粮\n"
                        f"  • 检查ID是否正确\n\n"
                        f"链路：{query_route}"
                    ),
                    "data": None,
                    "route": query_route
                }
        
        elif gift_ids is not None and len(gift_ids) > 0:
            # 批量按ID查询
            from business_logic.gift.gift_types import GiftType, GIFT_TYPE_NAMES

            if use_proxy:
                try:
                    results = _mongo_proxy_query(collections["gifts"], {"gift_id": {"$in": gift_ids}})
                    logger.info("query_gift_info(batch) 走 Mongo Proxy")
                except Exception as e:
                    logger.warning(f"query_gift_info(batch) 代理查询失败: {e}")
                    if not proxy_fallback_direct:
                        raise Exception(f"Mongo proxy 批量查询礼物失败: {str(e)}")
                    query_route = "direct"
                    client = get_mongo_client()
                    db_name = config.get("database", "fm")
                    db = client[db_name]
                    collection = db[collections["gifts"]]
                    results = list(collection.find({"gift_id": {"$in": gift_ids}}))
                    client.close()
            else:
                results = list(collection.find({"gift_id": {"$in": gift_ids}}))
                client.close()
            
            if results:
                gifts = []
                for result in results:
                    gift_type_value = result.get("type")
                    # 将数字类型转换为枚举
                    try:
                        gift_type_enum = GiftType(gift_type_value)
                        gift_type_name = GIFT_TYPE_NAMES.get(gift_type_enum, f"未知类型({gift_type_value})")
                    except (ValueError, KeyError):
                        gift_type_name = f"未知类型({gift_type_value})"
                    
                    gifts.append({
                        "gift_id": result.get("gift_id"),
                        "name": result.get("name"),
                        "type": gift_type_value,
                        "type_name": gift_type_name,
                        "price": result.get("price"),
                        "point": result.get("point"),
                        "order": result.get("order"),
                        "icon": result.get("icon"),
                        "icon_active": result.get("icon_active"),
                        "intro": result.get("intro"),
                        "comboable": result.get("comboable"),
                        "added_time": result.get("added_time").isoformat() if hasattr(result.get("added_time"), 'isoformat') else str(result.get("added_time"))
                    })
                
                # 按礼物ID排序
                gifts.sort(key=lambda x: x["gift_id"])
                
                # 检查是否有未找到的礼物
                found_ids = {g["gift_id"] for g in gifts}
                missing_ids = [gid for gid in gift_ids if gid not in found_ids]
                
                message = f"✅ 成功查询 {len(gifts)}/{len(gift_ids)} 个礼物"
                if missing_ids:
                    message += f"\n⚠️ 未找到的礼物ID: {', '.join(map(str, missing_ids))}"
                message += f"\n链路：{query_route}"
                
                return {
                    "success": True,
                    "message": message,
                    "data": gifts,
                    "total": len(gifts),
                    "missing_ids": missing_ids,
                    "route": query_route
                }
            else:
                return {
                    "success": False,
                    "message": (
                        f"❌ 未找到任何礼物\n\n"
                        f"查询ID: {', '.join(map(str, gift_ids))}\n\n"
                        f"💡 建议：\n"
                        f"  • 检查礼物ID是否正确\n"
                        f"  • 使用名称搜索：查询礼物猫粮\n\n"
                        f"链路：{query_route}"
                    ),
                    "data": [],
                    "total": 0,
                    "route": query_route
                }
        
        elif gift_name is not None and gift_name.strip():
            # 检查是否是通用词
            if gift_name.strip() in generic_terms:
                # 从配置文件加载帮助消息
                help_message = QueryConfigLoader.get_help_message("generic_term")
                
                return {
                    "success": False,
                    "message": help_message,
                    "data": None,
                    "route": query_route
                }
            
            # 按名称模糊查询
            regex = gift_name.strip()
            query = {"name": {"$regex": regex, "$options": "i"}}  # 不区分大小写

            if use_proxy:
                try:
                    proxy_results = _mongo_proxy_query(collections["gifts"], query)
                    # 代理查询不支持 projection/limit，客户端做裁剪与字段过滤
                    results = []
                    for item in proxy_results[:limit]:
                        results.append({
                            "gift_id": item.get("gift_id"),
                            "name": item.get("name"),
                            "type": item.get("type"),
                            "price": item.get("price"),
                            "intro": item.get("intro", "")
                        })
                    logger.info("query_gift_info(name) 走 Mongo Proxy")
                except Exception as e:
                    logger.warning(f"query_gift_info(name) 代理查询失败: {e}")
                    if not proxy_fallback_direct:
                        raise Exception(f"Mongo proxy 名称查询礼物失败: {str(e)}")
                    query_route = "direct"
                    client = get_mongo_client()
                    db_name = config.get("database", "fm")
                    db = client[db_name]
                    collection = db[collections["gifts"]]
                    results = list(collection.find(
                        query,
                        {"gift_id": 1, "name": 1, "type": 1, "price": 1, "intro": 1}
                    ).limit(limit))
                    client.close()
            else:
                results = list(collection.find(
                    query,
                    {"gift_id": 1, "name": 1, "type": 1, "price": 1, "intro": 1}
                ).limit(limit))
                client.close()
            
            if results:
                # 导入礼物类型映射
                from business_logic.gift.gift_types import GiftType, GIFT_TYPE_NAMES
                
                gifts = []
                for result in results:
                    gift_type_value = result.get("type")
                    # 将数字类型转换为枚举和名称
                    try:
                        gift_type_enum = GiftType(gift_type_value)
                        gift_type_name = GIFT_TYPE_NAMES.get(gift_type_enum, f"未知类型({gift_type_value})")
                    except (ValueError, KeyError):
                        gift_type_name = f"未知类型({gift_type_value})"
                    
                    gifts.append({
                        "gift_id": result.get("gift_id"),
                        "name": result.get("name"),
                        "type": result.get("type"),
                        "type_name": gift_type_name,
                        "price": result.get("price"),
                        "intro": result.get("intro", "")
                    })
                
                # 按礼物ID排序
                gifts.sort(key=lambda x: x["gift_id"])
                
                return {
                    "success": True,
                    "message": f"✅ 找到 {len(gifts)} 个匹配的礼物\n链路：{query_route}",
                    "data": gifts,
                    "total": len(gifts),
                    "route": query_route
                }
            else:
                return {
                    "success": False,
                    "message": (
                        f"❌ 未找到包含 '{gift_name}' 的礼物\n\n"
                        f"💡 建议：\n"
                        f"  • 尝试使用更短的关键词\n"
                        f"  • 检查拼写是否正确\n"
                        f"  • 使用礼物ID查询：查询礼物301的信息\n\n"
                        f"链路：{query_route}"
                    ),
                    "data": [],
                    "total": 0,
                    "route": query_route
                }
        else:
            # 无参数时，从配置文件加载帮助消息
            help_message = QueryConfigLoader.get_help_message("no_params")
            
            return {
                "success": False,
                "message": help_message,
                "data": None,
                "route": query_route
            }
            
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接 MongoDB 查询礼物信息: {e}")
        return {
            "success": False,
            "message": f"无法连接 MongoDB: {str(e)}",
            "data": None
        }
    except Exception as e:
        logger.error(f"查询礼物信息时发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"查询失败: {str(e)}",
            "data": None
        }


def insert_user_item(user_id: int, gift_id: int, num: int, start_time: int, end_time: int, gift_type: int) -> str:
    """
    插入用户背包物品到 MongoDB
    查询 MongoDB: fm.test_user_items 集合
    
    Args:
        user_id: 用户ID
        gift_id: 礼物ID
        num: 数量
        start_time: 开始时间戳
        end_time: 结束时间戳
        gift_type: 礼物类型（3=免费礼物，4=白给礼物）
    
    Returns:
        插入的文档ID
    """
    collections = get_mongo_collections()
    if _mongo_proxy_strict_only() and not _mongo_proxy_ready():
        raise Exception("Mongo Proxy 已启用且禁止回退，但代理配置不完整或不可用")
    document = {
        "type": gift_type,
        "user_id": user_id,
        "start_time": start_time,
        "end_time": end_time,
        "gift_id": gift_id,
        "num": num,
        "gain_num": num
    }

    if _mongo_proxy_ready():
        try:
            inserted_id = _mongo_proxy_insert(collections["user_items"], document)
            logger.info("insert_user_item 走 Mongo Proxy")
            return inserted_id
        except Exception as e:
            cfg = _get_mongo_proxy_config()
            logger.warning(f"insert_user_item 代理插入失败: {e}")
            if not cfg["fallback_direct"]:
                raise Exception(f"Mongo proxy 插入背包记录失败: {str(e)}")

    try:
        client = get_mongo_client()
        config = get_mongo_config()
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["user_items"]]

        result = collection.insert_one(document)
        client.close()
        return str(result.inserted_id)
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接 MongoDB 插入用户背包物品: {e}")
        raise Exception(f"无法连接 MongoDB 插入用户背包物品: {str(e)}")
    except Exception as e:
        logger.error(f"插入用户背包物品时发生错误: {e}")
        raise Exception(f"插入用户背包物品时发生错误: {str(e)}")


def delete_user_item_by_id(item_id: str) -> bool:
    """
    按 _id 删除用户背包物品
    
    Args:
        item_id: Mongo ObjectId 字符串
    
    Returns:
        是否删除成功
    """
    collections = get_mongo_collections()
    if _mongo_proxy_strict_only() and not _mongo_proxy_ready():
        raise Exception("Mongo Proxy 已启用且禁止回退，但代理配置不完整或不可用")
    if _mongo_proxy_ready():
        try:
            deleted = _mongo_proxy_delete_by_id(collections["user_items"], item_id)
            logger.info("delete_user_item_by_id 走 Mongo Proxy")
            return deleted
        except Exception as e:
            cfg = _get_mongo_proxy_config()
            logger.warning(f"delete_user_item_by_id 代理删除失败: {e}")
            if not cfg["fallback_direct"]:
                raise Exception(f"Mongo proxy 删除背包记录失败: {str(e)}")

    try:
        client = get_mongo_client()
        config = get_mongo_config()
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["user_items"]]

        result = collection.delete_one({"_id": ObjectId(item_id)})
        client.close()
        return result.deleted_count > 0
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接 MongoDB 删除背包记录: {e}")
        raise Exception(f"无法连接 MongoDB 删除背包记录: {str(e)}")
    except Exception as e:
        logger.error(f"删除背包记录时发生错误: {e}")
        raise Exception(f"删除背包记录时发生错误: {str(e)}")


def test_mongo_connection() -> bool:
    """测试 MongoDB 连接"""
    try:
        client = get_mongo_client()
        client.server_info()
        client.close()
        return True
    except Exception as e:
        logger.error(f"MongoDB 连接失败: {e}")
        return False
