"""
奖池配置查询服务
参考 MaoerProject02/core/pool/pool_service.py
支持查询随机礼物/幸运礼物/超能魔方奖池配置
"""
import os
import logging
from typing import Optional, Dict, Any, Union, List
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from bson import ObjectId
from dotenv import load_dotenv

from business_logic.common.mongo_db import get_mongo_client, get_mongo_config, get_mongo_collections
from utils.message_formatter import MessageFormatter

logger = logging.getLogger(__name__)
load_dotenv()

# MongoDB 仅支持 8 字节有符号整数，最大值为 2^63 - 1
MONGODB_MAX_INT = 2**63 - 1


def _get_pool_collection(db):
    """
    获取奖池集合
    
    Args:
        db: MongoDB数据库实例
        
    Returns:
        奖池集合实例
    """
    collections = get_mongo_collections()
    pool_collection_name = collections.get('pool', 'test_gift_draw_pool')
    return db[pool_collection_name]


def query_gifts_info(gift_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    批量查询礼物的名称和钻石数
    
    Args:
        gift_ids: 礼物ID列表
    
    Returns:
        字典，key为礼物ID，value为包含name和diamond的字典
    """
    if not gift_ids:
        return {}
    
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        collections = get_mongo_collections()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["gifts"]]
        
        # 查询所有礼物信息（注意：MongoDB中钻石数字段是price，不是diamond）
        query = {"gift_id": {"$in": gift_ids}}
        results = list(collection.find(query, {"gift_id": 1, "name": 1, "price": 1}))
        client.close()
        
        # 构建结果字典
        gifts_info = {}
        for result in results:
            gift_id = result.get("gift_id")
            if gift_id:
                gifts_info[gift_id] = {
                    "name": result.get("name", "未知"),
                    "diamond": result.get("price", 0)  # MongoDB中钻石数字段是price
                }
        
        # 对于未查询到的礼物，设置默认值
        for gift_id in gift_ids:
            if gift_id not in gifts_info:
                gifts_info[gift_id] = {
                    "name": "未知",
                    "diamond": 0
                }
        
        return gifts_info
    except Exception as e:
        logger.error(f"查询礼物信息失败: {e}", exc_info=True)
        # 如果查询失败，返回默认值
        return {gift_id: {"name": "未知", "diamond": 0} for gift_id in gift_ids}


def query_gifts_by_name(gift_name: str, limit: int = 10) -> Dict[str, Any]:
    """
    根据礼物名称（支持模糊查询）查询礼物信息
    
    Args:
        gift_name: 礼物名称（支持模糊匹配）
        limit: 最多返回的结果数量，默认10
    
    Returns:
        查询结果字典，包含success、message和data字段
    """
    # 从配置文件加载通用词列表
    from business_logic.common.query_config_loader import QueryConfigLoader
    generic_terms = QueryConfigLoader.get_generic_terms()
    
    if not gift_name or not gift_name.strip():
        help_message = QueryConfigLoader.get_help_message("no_params")
        
        return {
            "success": False,
            "message": help_message,
            "data": []
        }
    
    # 检查是否是通用词
    if gift_name.strip() in generic_terms:
        help_message = QueryConfigLoader.get_help_message("generic_term")
        
        return {
            "success": False,
            "message": help_message,
            "data": []
        }
    
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        collections = get_mongo_collections()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        collection = db[collections["gifts"]]
        
        # 使用 Mongo 正则进行模糊匹配
        regex = gift_name.strip()
        query = {"name": {"$regex": regex}}
        
        # 查询礼物信息，限制返回数量
        results = list(collection.find(
            query, 
            {"gift_id": 1, "name": 1, "price": 1}
        ).limit(limit))
        
        client.close()
        
        if not results:
            return {
                "success": False,
                "message": f"❌ 未找到包含 '{gift_name}' 的礼物",
                "data": []
            }
        
        # 构建结果列表
        gifts_info = []
        for result in results:
            gifts_info.append({
                "gift_id": result.get("gift_id"),
                "name": result.get("name", "未知"),
                "price": result.get("price", 0)
            })
        
        # 按礼物ID排序
        gifts_info.sort(key=lambda x: x["gift_id"])
        
        return {
            "success": True,
            "message": f"✅ 找到 {len(gifts_info)} 个包含 '{gift_name}' 的礼物",
            "data": gifts_info,
            "count": len(gifts_info)
        }
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接MongoDB查询礼物信息: {e}")
        return {
            "success": False,
            "message": f"❌ 无法连接MongoDB查询礼物信息。错误详情: {str(e)}",
            "data": []
        }
    except Exception as e:
        logger.error(f"查询礼物信息时发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 查询礼物信息时发生错误: {str(e)}",
            "data": []
        }


def query_pool_config_by_gift_id(gift_id: int) -> Dict[str, Any]:
    """
    通过礼物ID查询奖池配置（返回所有匹配的奖池）
    
    Args:
        gift_id: 礼物ID
    
    Returns:
        查询结果字典，包含success、message和data字段（data为列表）
    """
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        
        # 从配置文件获取奖池集合名称
        from business_logic.common.mongo_db import get_mongo_collections
        collections = get_mongo_collections()
        pool_collection_name = collections.get('pool', 'test_gift_draw_pool')
        collection = db[pool_collection_name]
        
        # 查询奖池配置
        query = {
            "$or": [
                {"gift_id": gift_id},
                {"giftId": gift_id},
                {"gift_id_list": gift_id},
                {"gifts": {"$elemMatch": {"gift_id": gift_id}}},
                {"gifts": {"$elemMatch": {"giftId": gift_id}}},
                {"gifts": gift_id},
            ]
        }
        
        results = list(collection.find(query))
        client.close()
        
        if results:
            # 转换所有结果的ObjectId为字符串，并添加保底信息和概率计算
            pools_data = []
            for result in results:
                # 转换ObjectId为字符串
                if "_id" in result:
                    result["_id"] = str(result["_id"])
                
                # 检查是否有保底必中
                has_guarantee = "miss_limit" in result and "ssr_id" in result
                
                # 获取gift_num（抽数）
                gift_num = result.get("gift_num", 1)
                
                # 计算概率
                rates = result.get("rates", {})
                probabilities = {}
                if rates:
                    # 批量查询礼物的名称和钻石数
                    gift_ids_list = [int(gid) for gid in rates.keys()]
                    gifts_info = query_gifts_info(gift_ids_list)
                    
                    # 计算总权重
                    total_weight = sum(rates.values())
                    if total_weight > 0:
                        # 计算每个奖品的概率（百分比）
                        for gift_id_str, weight in rates.items():
                            gift_id_int = int(gift_id_str)
                            probability = (weight / total_weight) * 100
                            gift_info = gifts_info.get(gift_id_int, {"name": "未知", "diamond": 0})
                            # 保留4位小数
                            probabilities[gift_id_str] = {
                                "weight": weight,
                                "probability": round(probability, 4),
                                "name": gift_info.get("name", "未知"),
                                "diamond": gift_info.get("diamond", 0)
                            }
                        # 按礼物ID降序排序
                        probabilities = dict(sorted(probabilities.items(), key=lambda x: int(x[0]), reverse=True))
                
                pool_info = {
                    "pool_data": result,
                    "pool_id": result.get("pool_id"),
                    "gift_num": gift_num,
                    "has_guarantee": has_guarantee,
                    "miss_limit": result.get("miss_limit"),
                    "ssr_id": result.get("ssr_id"),
                    "rates": rates,
                    "probabilities": probabilities,
                }
                pools_data.append(pool_info)
            
            return {
                "success": True,
                "message": f"✅ 找到 {len(pools_data)} 个奖池配置（礼物ID: {gift_id}）",
                "data": pools_data,
                "count": len(pools_data),
            }
        else:
            return {
                "success": False,
                "message": f"❌ 未找到礼物ID {gift_id} 对应的奖池配置",
                "data": None,
                "count": 0,
            }
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接MongoDB查询奖池配置: {e}")
        return {
            "success": False,
            "message": f"❌ 无法连接MongoDB查询奖池配置。错误详情: {str(e)}",
            "data": None,
            "count": 0,
        }
    except Exception as e:
        logger.error(f"查询奖池配置时发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 查询奖池配置时发生错误: {str(e)}",
            "data": None,
            "count": 0,
        }



def query_pool_config_by_pool_id(pool_id: Union[int, str]) -> Dict[str, Any]:
    """
    通过奖池ID查询奖池配置
    
    Args:
        pool_id: 奖池ID（可以是整数或字符串格式的ObjectId）
    
    Returns:
        查询结果字典，包含success、message和data字段
    """
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        
        # 从配置文件获取奖池集合
        collection = _get_pool_collection(db)
        
        # 查询奖池配置
        try:
            # 尝试将pool_id转换为ObjectId（如果是24位十六进制字符串）
            if isinstance(pool_id, str) and len(pool_id) == 24:
                object_id = ObjectId(pool_id)
                query = {
                    "$or": [
                        {"pool_id": pool_id},
                        {"poolId": pool_id},
                        {"id": pool_id},
                        {"_id": object_id},
                        {"_id": pool_id},
                    ]
                }
            else:
                query = {
                    "$or": [
                        {"pool_id": pool_id},
                        {"poolId": pool_id},
                        {"id": pool_id},
                        {"_id": pool_id},
                    ]
                }
        except:
            # 如果转换失败，使用普通查询
            query = {
                "$or": [
                    {"pool_id": pool_id},
                    {"poolId": pool_id},
                    {"id": pool_id},
                    {"_id": pool_id},
                ]
            }
        
        result = collection.find_one(query)
        client.close()
        
        if result:
            # 转换ObjectId为字符串
            if "_id" in result:
                result["_id"] = str(result["_id"])
            
            # 检查是否有保底必中
            has_guarantee = "miss_limit" in result and "ssr_id" in result
            
            # 获取gift_num（抽数）
            gift_num = result.get("gift_num", 1)
            
            # 计算概率
            rates = result.get("rates", {})
            probabilities = {}
            if rates:
                # 批量查询礼物的名称和钻石数
                gift_ids_list = [int(gid) for gid in rates.keys()]
                gifts_info = query_gifts_info(gift_ids_list)
                
                # 计算总权重
                total_weight = sum(rates.values())
                if total_weight > 0:
                    # 计算每个奖品的概率（百分比）
                    for gift_id_str, weight in rates.items():
                        gift_id_int = int(gift_id_str)
                        probability = (weight / total_weight) * 100
                        gift_info = gifts_info.get(gift_id_int, {"name": "未知", "diamond": 0})
                        # 保留4位小数
                        probabilities[gift_id_str] = {
                            "weight": weight,
                            "probability": round(probability, 4),
                            "name": gift_info.get("name", "未知"),
                            "diamond": gift_info.get("diamond", 0)
                        }
                    # 按礼物ID降序排序
                    probabilities = dict(sorted(probabilities.items(), key=lambda x: int(x[0]), reverse=True))
            
            pool_info = {
                "pool_data": result,
                "pool_id": result.get("pool_id"),
                "gift_num": gift_num,
                "has_guarantee": has_guarantee,
                "miss_limit": result.get("miss_limit"),
                "ssr_id": result.get("ssr_id"),
                "rates": rates,
                "probabilities": probabilities,
            }
            
            return {
                "success": True,
                "message": f"✅ 找到奖池配置（奖池ID: {pool_id}）",
                "data": pool_info,
                "has_guarantee": has_guarantee,
                "miss_limit": result.get("miss_limit"),
                "ssr_id": result.get("ssr_id"),
            }
        else:
            return {
                "success": False,
                "message": f"❌ 未找到奖池ID {pool_id} 对应的奖池配置",
                "data": None,
            }
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接MongoDB查询奖池配置: {e}")
        return {
            "success": False,
            "message": f"❌ 无法连接MongoDB查询奖池配置。错误详情: {str(e)}",
            "data": None,
        }
    except Exception as e:
        logger.error(f"查询奖池配置时发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 查询奖池配置时发生错误: {str(e)}",
            "data": None,
        }


def query_pool_config(gift_id: Optional[int] = None, pool_id: Optional[Union[int, str]] = None) -> Dict[str, Any]:
    """
    查询奖池配置（支持通过礼物ID或奖池ID查询）
    
    Args:
        gift_id: 礼物ID（可选）
        pool_id: 奖池ID（可选）
    
    Returns:
        查询结果字典
    """
    if gift_id:
        return query_pool_config_by_gift_id(gift_id)
    elif pool_id:
        return query_pool_config_by_pool_id(pool_id)
    else:
        return {
            "success": False,
            "message": MessageFormatter.missing_param_error(
                param_name="查询条件",
                param_description="查询条件（gift_id 或 pool_id）",
                examples=[
                    "查询礼物80103的奖池配置",
                    "查询奖池257的配置"
                ]
            ),
            "data": None,
        }


def update_pool_gift_weight_to_max(pool_id: int, gift_id: int, gift_num: Optional[int] = None) -> Dict[str, Any]:
    """
    将奖池中某个礼物的权重改为最大（在现有权重后加6个0，即乘以1000000）
    
    Args:
        pool_id: 奖池ID
        gift_id: 礼物ID
        gift_num: 抽数（可选，用于筛选特定抽数的奖池）
    
    Returns:
        修改结果字典
    """
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        
        # 从配置文件获取奖池集合
        collection = _get_pool_collection(db)
        
        # 查询奖池配置
        query = {"pool_id": pool_id}
        if gift_num is not None:
            query["gift_num"] = gift_num
        
        pool_config = collection.find_one(query)
        
        if not pool_config:
            client.close()
            return {
                "success": False,
                "message": f"❌ 未找到奖池配置（pool_id={pool_id}" + (f", gift_num={gift_num}" if gift_num else "") + "）",
            }
        
        # 获取rates字段
        rates = pool_config.get("rates", {})
        if not rates:
            client.close()
            return {
                "success": False,
                "message": f"❌ 奖池配置中没有rates字段",
            }
        
        # 检查礼物ID是否存在
        gift_id_str = str(gift_id)
        if gift_id_str not in rates:
            client.close()
            gift_num_info = f"{gift_num}抽奖池" if gift_num else "奖池"
            return {
                "success": False,
                "message": f"❌ {gift_num_info}（pool_id={pool_id}）中不存在礼物ID {gift_id}",
            }
        
        # 获取当前权重
        current_weight = rates[gift_id_str]
        
        # 检查权重是否已经是最大值
        if current_weight >= MONGODB_MAX_INT // 10:
            client.close()
            return {
                "success": True,
                "message": f"✅ 礼物 {gift_id} 的权重已经是最大值（{current_weight}），无需修改",
                "pool_id": pool_id,
                "gift_id": gift_id,
                "current_weight": current_weight,
                "already_max": True,
            }
        
        # 计算新权重（加6个0，即乘以1000000），且不超过 MongoDB 8 字节整数上限
        new_weight = min(current_weight * 1000000, MONGODB_MAX_INT)
        
        # 检查新权重是否等于当前权重
        if new_weight == current_weight:
            client.close()
            return {
                "success": True,
                "message": f"✅ 礼物 {gift_id} 的权重已经是最大值（{current_weight}），无需修改",
                "pool_id": pool_id,
                "gift_id": gift_id,
                "current_weight": current_weight,
                "already_max": True,
            }
        
        # 更新rates字段
        rates[gift_id_str] = new_weight
        
        # 获取文档ID
        doc_id = str(pool_config["_id"])
        update_data = {"rates": rates}
        
        # 尝试使用代理更新
        from business_logic.common.mongo_db import _mongo_proxy_ready, _mongo_proxy_update_by_id, _get_mongo_proxy_config, get_mongo_collections
        
        collections = get_mongo_collections()
        pool_collection_name = collections.get("pool", "test_gift_draw_pool")
        
        if _mongo_proxy_ready():
            try:
                success = _mongo_proxy_update_by_id(pool_collection_name, doc_id, update_data)
                client.close()
                logger.info("update_pool_gift_weight_to_max 走 Mongo Proxy")
                
                if success:
                    return {
                        "success": True,
                        "message": f"✅ 成功将奖池 {pool_id} 中礼物 {gift_id} 的权重从 {current_weight} 改为 {new_weight}（代理）",
                        "pool_id": pool_id,
                        "gift_id": gift_id,
                        "old_weight": current_weight,
                        "new_weight": new_weight,
                        "route": "proxy"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"❌ 更新失败，权重未发生变化",
                    }
            except Exception as e:
                cfg = _get_mongo_proxy_config()
                logger.warning(f"update_pool_gift_weight_to_max 代理更新失败: {e}")
                if not cfg["fallback_direct"]:
                    client.close()
                    raise Exception(f"Mongo proxy 更新奖池配置失败: {str(e)}")
                # 继续执行直连更新
        
        # 直连更新MongoDB
        update_result = collection.update_one(
            {"_id": pool_config["_id"]},
            {"$set": {"rates": rates}}
        )
        
        client.close()
        
        if update_result.modified_count > 0:
            return {
                "success": True,
                "message": f"✅ 成功将奖池 {pool_id} 中礼物 {gift_id} 的权重从 {current_weight} 改为 {new_weight}",
                "pool_id": pool_id,
                "gift_id": gift_id,
                "old_weight": current_weight,
                "new_weight": new_weight,
                "route": "direct"
            }
        else:
            return {
                "success": False,
                "message": f"❌ 更新失败，权重未发生变化（当前值：{current_weight}，尝试修改为：{new_weight}）",
            }
            
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接MongoDB更新奖池配置: {e}")
        return {
            "success": False,
            "message": f"❌ 无法连接MongoDB更新奖池配置。错误详情: {str(e)}",
        }
    except Exception as e:
        logger.error(f"更新奖池配置时发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 更新奖池配置时发生错误: {str(e)}",
        }


def update_pool_gift_weight(
    pool_id: int, gift_id: int, weight: int, gift_num: Optional[int] = None
) -> Dict[str, Any]:
    """
    将奖池中某个礼物的权重设为指定值（用于恢复权重等场景）

    Args:
        pool_id: 奖池ID
        gift_id: 礼物ID
        weight: 目标权重值
        gift_num: 抽数（可选，用于筛选特定抽数的奖池）
    
    Returns:
        修改结果字典
    """
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        
        # 从配置文件获取奖池集合
        collection = _get_pool_collection(db)

        query = {"pool_id": pool_id}
        if gift_num is not None:
            query["gift_num"] = gift_num

        pool_config = collection.find_one(query)
        if not pool_config:
            client.close()
            return {
                "success": False,
                "message": f"❌ 未找到奖池配置（pool_id={pool_id}"
                + (f", gift_num={gift_num}" if gift_num else "") + "）",
            }

        rates = pool_config.get("rates", {})
        gift_id_str = str(gift_id)
        if gift_id_str not in rates:
            client.close()
            return {
                "success": False,
                "message": f"❌ 奖池（pool_id={pool_id}）中不存在礼物ID {gift_id}",
            }

        old_weight = rates[gift_id_str]
        rates[gift_id_str] = weight
        
        # 获取文档ID
        doc_id = str(pool_config["_id"])
        update_data = {"rates": rates}
        
        # 尝试使用代理更新
        from business_logic.common.mongo_db import _mongo_proxy_ready, _mongo_proxy_update_by_id, _get_mongo_proxy_config, get_mongo_collections
        
        collections = get_mongo_collections()
        pool_collection_name = collections.get("pool", "test_gift_draw_pool")
        
        if _mongo_proxy_ready():
            try:
                success = _mongo_proxy_update_by_id(pool_collection_name, doc_id, update_data)
                client.close()
                logger.info("update_pool_gift_weight 走 Mongo Proxy")
                
                if success:
                    return {
                        "success": True,
                        "message": f"✅ 成功将奖池 {pool_id} 中礼物 {gift_id} 的权重从 {old_weight} 改为 {weight}（代理）",
                        "pool_id": pool_id,
                        "gift_id": gift_id,
                        "old_weight": old_weight,
                        "new_weight": weight,
                        "route": "proxy"
                    }
                else:
                    return {
                        "success": False,
                        "message": "❌ 更新失败，可能权重未发生变化",
                    }
            except Exception as e:
                cfg = _get_mongo_proxy_config()
                logger.warning(f"update_pool_gift_weight 代理更新失败: {e}")
                if not cfg["fallback_direct"]:
                    client.close()
                    raise Exception(f"Mongo proxy 更新奖池配置失败: {str(e)}")
                # 继续执行直连更新
        
        # 直连更新MongoDB
        update_result = collection.update_one(
            {"_id": pool_config["_id"]},
            {"$set": {"rates": rates}},
        )
        client.close()

        if update_result.modified_count > 0:
            return {
                "success": True,
                "message": f"✅ 成功将奖池 {pool_id} 中礼物 {gift_id} 的权重从 {old_weight} 改为 {weight}",
                "pool_id": pool_id,
                "gift_id": gift_id,
                "old_weight": old_weight,
                "new_weight": weight,
                "route": "direct"
            }
        return {
            "success": False,
            "message": "❌ 更新失败，可能权重未发生变化",
        }
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接MongoDB更新奖池配置: {e}")
        return {
            "success": False,
            "message": f"❌ 无法连接MongoDB更新奖池配置。错误详情: {str(e)}",
        }
    except Exception as e:
        logger.error(f"更新奖池配置时发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 更新奖池配置时发生错误: {str(e)}",
        }


def update_pool_ssr_weight_to_zero(pool_id: int, ssr_id: int, gift_num: Optional[int] = None) -> Dict[str, Any]:
    """
    将奖池中保底大奖的权重改为0
    
    Args:
        pool_id: 奖池ID
        ssr_id: 保底大奖ID
        gift_num: 抽数（可选，用于筛选特定抽数的奖池）
    
    Returns:
        修改结果字典
    """
    try:
        client = get_mongo_client()
        config = get_mongo_config()
        
        db_name = config.get("database", "fm")
        db = client[db_name]
        
        # 从配置文件获取奖池集合
        collection = _get_pool_collection(db)
        
        # 查询奖池配置
        query = {"pool_id": pool_id}
        if gift_num is not None:
            query["gift_num"] = gift_num
        
        pool_config = collection.find_one(query)
        
        if not pool_config:
            client.close()
            return {
                "success": False,
                "message": f"❌ 未找到奖池配置（pool_id={pool_id}" + (f", gift_num={gift_num}" if gift_num else "") + "）",
            }
        
        # 获取rates字段
        rates = pool_config.get("rates", {})
        if not rates:
            client.close()
            return {
                "success": False,
                "message": f"❌ 奖池配置中没有rates字段",
            }
        
        # 检查大奖ID是否存在
        ssr_id_str = str(ssr_id)
        if ssr_id_str not in rates:
            client.close()
            gift_num_info = f"{gift_num}抽奖池" if gift_num else "奖池"
            return {
                "success": False,
                "message": f"❌ {gift_num_info}（pool_id={pool_id}）中不存在大奖ID {ssr_id}",
            }
        
        # 获取当前权重
        old_weight = rates[ssr_id_str]
        
        # 如果已经是0，不需要更新
        if old_weight == 0:
            client.close()
            return {
                "success": True,
                "message": f"✅ 大奖ID {ssr_id} 的权重已经是0，无需更新",
                "pool_id": pool_id,
                "ssr_id": ssr_id,
                "old_weight": 0,
                "new_weight": 0,
            }
        
        # 更新权重为0
        rates[ssr_id_str] = 0
        
        # 获取文档ID
        doc_id = str(pool_config["_id"])
        update_data = {"rates": rates}
        
        # 尝试使用代理更新
        from business_logic.common.mongo_db import _mongo_proxy_ready, _mongo_proxy_update_by_id, _get_mongo_proxy_config, get_mongo_collections
        
        collections = get_mongo_collections()
        pool_collection_name = collections.get("pool", "test_gift_draw_pool")
        
        if _mongo_proxy_ready():
            try:
                success = _mongo_proxy_update_by_id(pool_collection_name, doc_id, update_data)
                client.close()
                logger.info("update_pool_ssr_weight_to_zero 走 Mongo Proxy")
                
                if success:
                    return {
                        "success": True,
                        "message": f"✅ 成功将奖池 {pool_id} 中大奖 {ssr_id} 的权重从 {old_weight} 改为 0（代理）",
                        "pool_id": pool_id,
                        "ssr_id": ssr_id,
                        "old_weight": old_weight,
                        "new_weight": 0,
                        "route": "proxy"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"❌ 更新失败，可能权重未发生变化",
                    }
            except Exception as e:
                cfg = _get_mongo_proxy_config()
                logger.warning(f"update_pool_ssr_weight_to_zero 代理更新失败: {e}")
                if not cfg["fallback_direct"]:
                    client.close()
                    raise Exception(f"Mongo proxy 更新奖池配置失败: {str(e)}")
                # 继续执行直连更新
        
        # 直连更新MongoDB
        update_result = collection.update_one(
            {"_id": pool_config["_id"]},
            {"$set": {"rates": rates}}
        )
        
        client.close()
        
        if update_result.modified_count > 0:
            return {
                "success": True,
                "message": f"✅ 成功将奖池 {pool_id} 中大奖 {ssr_id} 的权重从 {old_weight} 改为 0",
                "pool_id": pool_id,
                "ssr_id": ssr_id,
                "old_weight": old_weight,
                "new_weight": 0,
                "route": "direct"
            }
        else:
            return {
                "success": False,
                "message": f"❌ 更新失败，可能权重未发生变化",
            }
            
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"无法连接MongoDB更新奖池配置: {e}")
        return {
            "success": False,
            "message": f"❌ 无法连接MongoDB更新奖池配置。错误详情: {str(e)}",
        }
    except Exception as e:
        logger.error(f"更新奖池配置时发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"❌ 更新奖池配置时发生错误: {str(e)}",
        }
