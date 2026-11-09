#!/usr/bin/env python3
"""
批量执行用户信息与验证码查询指令
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 所有测试指令
test_cases = [
    {
        "category": "4.1 正常查询",
        "commands": [
            "查询用户9075566的信息",
            "查询直播间9075367的用户id",
            "查询live@missevan.cn的用户信息",
            "查询手机号15000000490的用户信息",
            "查询验证码15000000490",
            "查询手机号15000000490的验证码",
            "查询用户9075566的验证码",
            "查询live@missevan.cn的验证码"
        ]
    },
    {
        "category": "4.2 异常场景",
        "commands": [
            "查询用户9999999的信息",
            "查询用户信息",
            "查询用户信息 live@test.com",
            "查询手机号15900000499的用户信息",
            "查询验证码"
        ]
    }
]

def execute_command(command, index, total):
    """执行单个指令"""
    print(f"\n{'='*80}")
    print(f"[{index}/{total}] 执行指令: {command}")
    print(f"{'='*80}")
    
    try:
        payload = {
            "business_code": "ear_test",
            "user_input": command,
            "context": {
                "operator": "batch_test",
                "env": "uat"
            }
        }
        
        response = requests.post(
            API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        result = response.json()
        
        # 打印结果
        if result.get('success'):
            print(f"✅ 成功")
            print(f"消息: {result.get('message', 'N/A')}")
            
            if result.get('data'):
                data = result['data']
                if isinstance(data, dict):
                    # 用户信息
                    if 'user_id' in data:
                        print(f"  - 用户ID: {data.get('user_id')}")
                    if 'username' in data:
                        print(f"  - 用户名: {data.get('username')}")
                    if 'email' in data:
                        print(f"  - 邮箱: {data.get('email')}")
                    if 'phone' in data:
                        print(f"  - 手机号: {data.get('phone')}")
                    # 验证码
                    if 'verify_code' in data:
                        print(f"  - 验证码: {data.get('verify_code')}")
                    if 'identifier' in data:
                        print(f"  - 标识: {data.get('identifier')}")
        else:
            print(f"❌ 失败")
            msg = result.get('message', 'N/A')
            # 只打印前200个字符
            if len(msg) > 200:
                msg = msg[:200] + "..."
            print(f"消息: {msg}")
            if result.get('error'):
                print(f"错误: {result['error']}")
        
        return {
            "command": command,
            "success": result.get('success', False),
            "message": result.get('message', ''),
            "skill_name": result.get('skill_name')
        }
        
    except Exception as e:
        print(f"❌ 执行异常: {str(e)}")
        return {
            "command": command,
            "success": False,
            "message": str(e),
            "skill_name": None
        }

def main():
    """主函数"""
    print("\n" + "="*80)
    print("开始批量执行用户信息与验证码查询指令测试")
    print("="*80)
    
    all_results = []
    total_commands = sum(len(tc['commands']) for tc in test_cases)
    current_index = 0
    
    for test_case in test_cases:
        category = test_case['category']
        commands = test_case['commands']
        
        print(f"\n\n{'#'*80}")
        print(f"# {category}")
        print(f"{'#'*80}")
        
        category_results = []
        
        for command in commands:
            current_index += 1
            result = execute_command(command, current_index, total_commands)
            category_results.append(result)
            time.sleep(0.3)  # 避免请求过快
        
        all_results.append({
            "category": category,
            "results": category_results
        })
    
    # 打印汇总
    print(f"\n\n{'='*80}")
    print("执行汇总报告")
    print(f"{'='*80}")
    
    total_success = 0
    total_fail = 0
    
    for category_result in all_results:
        category = category_result['category']
        results = category_result['results']
        
        success_count = sum(1 for r in results if r['success'])
        fail_count = len(results) - success_count
        total_success += success_count
        total_fail += fail_count
        
        print(f"\n{category}:")
        print(f"  成功: {success_count}/{len(results)}")
        
        for r in results:
            status = "✅" if r['success'] else "❌"
            cmd_short = r['command'][:60] + "..." if len(r['command']) > 60 else r['command']
            print(f"  {status} {cmd_short}")
    
    print(f"\n{'='*80}")
    print(f"总计: 成功 {total_success}, 失败 {total_fail}, 总数 {total_success + total_fail}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
