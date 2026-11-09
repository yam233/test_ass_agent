#!/usr/bin/env python3
"""
批量查询用户手机号
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 用户ID列表
user_ids = [
    9075133, 9075123, 9075130, 9075369, 9075091, 9075129,
    9075124, 9075368, 9075380, 9075367, 9075095, 9075173,
    9075397, 9074509, 9075156, 10000002304, 10000000516, 10000001752
]

def query_user_info(user_id):
    """查询单个用户信息"""
    payload = {
        "business_code": "testops",
        "user_input": f"查询用户{user_id}的信息"
    }
    
    try:
        response = requests.post(API_URL, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                data = result.get("data", {})
                return {
                    "user_id": data.get("user_id"),
                    "username": data.get("username"),
                    "phone": data.get("phone"),
                    "email": data.get("email"),
                    "room_id": data.get("room_id"),
                    "success": True
                }
            else:
                return {
                    "user_id": user_id,
                    "error": result.get("message", "查询失败"),
                    "success": False
                }
        else:
            return {
                "user_id": user_id,
                "error": f"HTTP {response.status_code}",
                "success": False
            }
    except Exception as e:
        return {
            "user_id": user_id,
            "error": str(e),
            "success": False
        }

def main():
    """主函数"""
    print("=" * 80)
    print("批量查询用户手机号")
    print("=" * 80)
    
    results = []
    success_count = 0
    fail_count = 0
    
    for i, user_id in enumerate(user_ids, 1):
        print(f"\n[{i:2d}/{len(user_ids)}] 查询用户 {user_id}...")
        
        result = query_user_info(user_id)
        results.append(result)
        
        if result["success"]:
            success_count += 1
            print(f"  ✅ 用户ID: {result['user_id']}")
            print(f"     用户名: {result['username']}")
            print(f"     手机号: {result['phone']}")
            if result.get('email'):
                print(f"     邮箱: {result['email']}")
            if result.get('room_id'):
                print(f"     直播间: {result['room_id']}")
        else:
            fail_count += 1
            print(f"  ❌ 查询失败: {result['error']}")
        
        # 避免请求过快
        time.sleep(0.5)
    
    # 汇总结果
    print("\n" + "=" * 80)
    print("查询结果汇总")
    print("=" * 80)
    print(f"总数: {len(user_ids)}")
    print(f"成功: {success_count}")
    print(f"失败: {fail_count}")
    
    # 输出成功的用户信息表格
    if success_count > 0:
        print("\n📋 成功查询的用户信息:")
        print("-" * 80)
        print(f"{'用户ID':<12} {'用户名':<15} {'手机号':<18} {'直播间ID':<12}")
        print("-" * 80)
        
        for result in results:
            if result["success"]:
                user_id = result['user_id']
                username = result['username'] or 'N/A'
                phone = result['phone'] or 'N/A'
                room_id = result.get('room_id', 'N/A')
                
                print(f"{user_id:<12} {username:<15} {phone:<18} {room_id:<12}")
    
    # 输出失败的用户
    if fail_count > 0:
        print(f"\n❌ 查询失败的用户 ({fail_count}个):")
        for result in results:
            if not result["success"]:
                print(f"  - 用户ID {result['user_id']}: {result['error']}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()