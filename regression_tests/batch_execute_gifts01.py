#!/usr/bin/env python3
"""
批量执行礼物发放指令
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 所有测试指令
test_cases = [
    {
        "category": "1.1 专属Tab礼物发放",
        "commands": [
            "给用户9075566发礼物20123到专属tab",
            "给直播间9075367发礼物70123到专属tab，永久有效",
            "给直播间9075367发送礼物80103到专属tab"
        ]
    },
    {
        "category": "1.2 异常场景",
        "commands": [
            "发礼物20123到专属tab",
            "给用户9075566发礼物10123到专属tab",
            "给用户9075367发礼物201230到专属tab",
            "给用户90909090发礼物20123到专属tab"
        ]
    },
    {
        "category": "1.3 批量操作",
        "commands": [
            "给用户9075566，9075567，9075568发礼物20123到专属tab",
            "批量为直播间9075367，9075368发送礼物70123到专属tab"
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
                    if 'id' in data:
                        print(f"  - 发放ID: {data.get('id')}")
                        print(f"  - 用户/直播间: {data.get('element_id', data.get('room_id'))}")
                        print(f"  - 礼物ID: {data.get('gift_id')}")
                        print(f"  - 有效期: {data.get('duration', 'N/A')}")
                    # 批量发放结果
                    elif 'results' in data:
                        results = data['results']
                        success_count = sum(1 for r in results if r.get('success'))
                        print(f"  - 批量发放: 成功 {success_count}/{len(results)}")
                        for r in results:
                            status = "✅" if r.get('success') else "❌"
                            print(f"    {status} {r.get('message', 'N/A')}")
        else:
            print(f"❌ 失败")
            print(f"消息: {result.get('message', 'N/A')}")
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
    print("开始批量执行礼物发放指令测试")
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
