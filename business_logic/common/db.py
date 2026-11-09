"""
数据库连接模块
参考 MaoerProject02/core/common/db.py
"""
import json
import os
import pymysql
from typing import Optional, Dict, Any
import logging

from agent_core.skills.standard import DatabaseQuerySkill

logger = logging.getLogger(__name__)

# 加载数据库配置文件
_db_config_cache = None

def _load_db_config() -> Dict[str, Any]:
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


def get_db_config(db_type: str = "live") -> Dict[str, Any]:
    """
    获取数据库配置（从配置文件）
    
    Args:
        db_type: 数据库类型 (live/user)
    
    Returns:
        数据库配置字典
    """
    config = _load_db_config()
    
    if db_type == "user":
        user_config = config['mysql']['user_db']
        return {
            'host': user_config['host'],
            'port': user_config['port'],
            'user': user_config['user'],
            'password': user_config['password'],
            'database': user_config['database'],
            'charset': user_config['charset'],
            'connect_timeout': 30,
            'read_timeout': 30,
            'write_timeout': 30
        }
    else:  # live
        live_config = config['mysql']['live_db']
        return {
            'host': live_config['host'],
            'port': live_config['port'],
            'user': live_config['user'],
            'password': live_config['password'],
            'database': live_config['database'],
            'charset': live_config['charset'],
            'connect_timeout': 30,
            'read_timeout': 30,
            'write_timeout': 30
        }


def get_connection(db_type: str = "live"):
    """获取数据库连接"""
    config = get_db_config(db_type)
    return pymysql.connect(**config)


def execute_query(sql: str, params: tuple = None, db_type: str = "live") -> list:
    """
    执行查询语句
    返回查询结果列表
    """
    valid, error = DatabaseQuerySkill.validate_sql(sql)
    if not valid:
        raise ValueError(error)
    conn = get_connection(db_type)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
    finally:
        conn.close()


def execute_insert(sql: str, params: tuple, db_type: str = "live") -> int:
    """
    执行插入语句
    返回插入的行ID
    """
    conn = get_connection(db_type)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def execute_delete(sql: str, params: tuple = None, db_type: str = "live") -> int:
    """
    执行删除语句
    返回受影响的行数
    """
    conn = get_connection(db_type)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
    finally:
        conn.close()


def check_user_exists(user_id: int) -> bool:
    """
    检查用户ID是否存在
    查询 example_db.m_user 表
    """
    try:
        sql = "SELECT * FROM `m_user` WHERE id = %s"
        results = execute_query(sql, (user_id,), db_type="user")
        return len(results) > 0
    except Exception as e:
        logger.error(f"检查用户存在性失败: {e}")
        raise


def query_user_info(query_value: str) -> Optional[Dict[str, Any]]:
    """
    查询用户信息（统一入口）
    支持通过用户ID、手机号或邮箱查询
    """
    try:
        # 尝试作为用户ID查询（纯数字）
        if query_value.isdigit():
            sql = "SELECT id, mobile, email, region, username, ctime, iconurl FROM `m_user` WHERE id = %s"
            results = execute_query(sql, (int(query_value),), db_type="user")
            if results:
                return results[0]

        # 尝试作为手机号查询
        sql = "SELECT id, mobile, email, region, username, ctime, iconurl FROM `m_user` WHERE mobile = %s"
        results = execute_query(sql, (query_value,), db_type="user")
        if results:
            return results[0]

        # 尝试作为邮箱查询
        sql = "SELECT id, mobile, email, region, username, ctime, iconurl FROM `m_user` WHERE email = %s"
        results = execute_query(sql, (query_value,), db_type="user")
        if results:
            return results[0]

        return None
    except Exception as e:
        logger.error(f"查询用户信息失败: {e}")
        raise


def test_connection() -> bool:
    """测试数据库连接"""
    try:
        conn = get_connection()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return False
