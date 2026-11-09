#!/usr/bin/env python3
"""
数据库查询 MCP 服务器
直接查询 MySQL 数据库获取用户信息
"""
import os
import sys
from typing import Optional, Dict, Any
import pymysql
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 数据库配置
USER_DB_CONFIG = {
    'host': os.getenv('USER_DB_HOST'),
    'port': int(os.getenv('USER_DB_PORT', 3306)),
    'user': os.getenv('USER_DB_USER'),
    'password': os.getenv('USER_DB_PASSWORD'),
    'database': os.getenv('USER_DB_DATABASE'),
    'charset': os.getenv('USER_DB_CHARSET', 'utf8mb3')
}

LIVE_DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_DATABASE'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb3')
}


def get_user_db_connection():
    """获取用户数据库连接"""
    return pymysql.connect(**USER_DB_CONFIG)


def get_live_db_connection():
    """获取直播数据库连接"""
    return pymysql.connect(**LIVE_DB_CONFIG)


def query_user_info(
    user_id: Optional[int] = None,
    room_id: Optional[int] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None
) -> Dict[str, Any]:
    """
    查询用户信息
    
    Args:
        user_id: 用户ID
        room_id: 直播间ID
        email: 邮箱
        phone: 手机号
    
    Returns:
        用户信息字典
    """
    try:
        # 如果提供了 room_id，先查询对应的 user_id
        if room_id and not user_id:
            live_conn = get_live_db_connection()
            try:
                with live_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    sql = "SELECT user_id FROM room WHERE id = %s"
                    cursor.execute(sql, (room_id,))
                    result = cursor.fetchone()
                    if result:
                        user_id = result['user_id']
                    else:
                        return {
                            "success": False,
                            "message": f"直播间 {room_id} 不存在"
                        }
            finally:
                live_conn.close()
        
        # 查询用户信息
        user_conn = get_user_db_connection()
        try:
            with user_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # 构建查询条件
                conditions = []
                params = []
                
                if user_id:
                    conditions.append("id = %s")
                    params.append(user_id)
                elif email:
                    conditions.append("email = %s")
                    params.append(email)
                elif phone:
                    conditions.append("mobile = %s")
                    params.append(phone)
                else:
                    return {
                        "success": False,
                        "message": "必须提供 user_id、room_id、email 或 phone 中的至少一个参数"
                    }
                
                where_clause = " AND ".join(conditions)
                sql = f"SELECT id, username, mobile, region, email, ctime, iconurl FROM m_user WHERE {where_clause}"
                
                cursor.execute(sql, params)
                user = cursor.fetchone()
                
                if not user:
                    return {
                        "success": False,
                        "message": "用户不存在"
                    }
                
                # 查询直播间信息（如果有权限）
                room_info = None
                try:
                    if user['id']:
                        live_conn = get_live_db_connection()
                        try:
                            with live_conn.cursor(pymysql.cursors.DictCursor) as room_cursor:
                                room_sql = "SELECT id, name FROM room WHERE user_id = %s LIMIT 1"
                                room_cursor.execute(room_sql, (user['id'],))
                                room_info = room_cursor.fetchone()
                        finally:
                            live_conn.close()
                except Exception as e:
                    # 如果没有权限，跳过直播间查询
                    pass
                
                # 格式化手机号（带区号）
                phone_display = None
                if user['mobile']:
                    region = user['region'] if user['region'] else 86
                    phone_display = f"+{region} {user['mobile']}"
                
                # 格式化返回数据
                return {
                    "success": True,
                    "data": {
                        "user_id": user['id'],
                        "username": user['username'],
                        "phone": phone_display,
                        "email": user['email'] if user['email'] else None,
                        "room_id": room_info['id'] if room_info else None,
                        "room_name": room_info['name'] if room_info else None,
                        "created_at": user['ctime'] if user['ctime'] else None,
                        "icon_url": user['iconurl'] if user['iconurl'] else None
                    },
                    "message": "查询成功"
                }
        finally:
            user_conn.close()
            
    except Exception as e:
        return {
            "success": False,
            "message": f"查询失败: {str(e)}"
        }


def get_verify_code(
    phone: Optional[str] = None,
    user_id: Optional[int] = None,
    email: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取验证码（从 Redis 或数据库）
    
    Args:
        phone: 手机号
        user_id: 用户ID
        email: 邮箱
    
    Returns:
        验证码信息
    """
    # TODO: 实现从 Redis 查询验证码的逻辑
    # 这里先返回模拟数据
    return {
        "success": True,
        "data": {
            "code": "123456",
            "expire_time": "2026-02-17 15:00:00"
        },
        "message": "验证码查询功能待实现（需要 Redis 支持）"
    }


# MCP 服务器工具定义
TOOLS = [
    {
        "name": "query_user_info",
        "description": "查询用户信息（直接查询数据库）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "用户ID"
                },
                "room_id": {
                    "type": "integer",
                    "description": "直播间ID"
                },
                "email": {
                    "type": "string",
                    "description": "邮箱地址"
                },
                "phone": {
                    "type": "string",
                    "description": "手机号"
                }
            }
        }
    },
    {
        "name": "get_verify_code",
        "description": "获取验证码",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "手机号"
                },
                "user_id": {
                    "type": "integer",
                    "description": "用户ID"
                },
                "email": {
                    "type": "string",
                    "description": "邮箱地址"
                }
            }
        }
    }
]


def handle_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """处理工具调用"""
    if tool_name == "query_user_info":
        return query_user_info(**arguments)
    elif tool_name == "get_verify_code":
        return get_verify_code(**arguments)
    else:
        return {
            "success": False,
            "message": f"未知的工具: {tool_name}"
        }


if __name__ == "__main__":
    # 测试查询
    print("测试查询用户 9075333:")
    result = query_user_info(user_id=9075333)
    print(result)
