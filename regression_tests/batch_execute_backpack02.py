#!/usr/bin/env python3
"""
批量执行背包礼物发放指令
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 所有测试指令
test_cases = [
    {
        "category": "2.1 免费礼物到背包（3开头）",
        "commands": [
            "给用户9075566发礼物301到背包",
            "给用户9075566发5个礼物401到背包"
        ]
    },
    {
        "category": "2.2 异常场景",
        "commands": [
            "给用户9075566发礼物20123到背包",
            "发礼物301到背包",
            "给用户9075566发礼物到背包",
            "给用户9075566发礼物399999到背包",
            "给用户90999999发礼物301到背包"
        ]
    },
    {
        "category": "2.3 批量操作",
        "commands": [
            "给用户9075566发301，30140，40109到背包",
            "给用户9075566发10个301，20个30140，18个40109到背包",
            "给用户 9075566 发送 10 个礼物 301 到背包，给用户 9075567 发送 25 个礼物 401 到背包",
            "给用户9075566，9075567发10个礼物301"
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
            "business_code": "testops",
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
                    # 单个发放结果
                    if 'gift_id' in data and 'user_id' in data:
                        print(f"  - 用户ID: {data.get('user_id')}")
                        print(f"  - 礼物ID: {data.get('gift_id')}")
                        print(f"  - 数量: {data.get('count', 1)}")
                    # 批量发放结果
                    elif 'results' in data:
                        results = data['results']
                        success_count = sum(1 for r in results if r.get('success'))
                        print(f"  - 批量发放: 成功 {success_count}/{len(results)}")
                        for r in results:
                            status = "✅" if r.get('success') else "❌"
                            msg = r.get('message', 'N/A')
                            if len(msg) > 60:
                                msg = msg[:60] + "..."
                            print(f"    {status} {msg}")
                    # 多操作结果
                    elif 'operations' in data:
                        ops = data['operations']
                        success_count = sum(1 for op in ops if op.get('success'))
                        print(f"  - 多操作: 成功 {success_count}/{len(ops)}")
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
    print("开始批量执行背包礼物发放指令测试")
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
