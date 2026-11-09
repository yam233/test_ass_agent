#!/usr/bin/env python3
"""
批量执行礼物查询指令
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 所有测试指令
test_cases = [
    {
        "category": "3.1 正常+批量查询",
        "commands": [
            "查询礼物猫粮",
            "查询礼物 30001 的信息",
            "检查礼物20123的类型",
            "查询礼物20123和301的类型",
            "查询礼物20123和301的信息"
        ]
    },
    {
        "category": "3.2 异常场景",
        "commands": [
            "查询礼物信息",
            "查询礼物 400100 的信息",
            "检查礼物999999的类型",
            "检查礼物类型"
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
            msg = result.get('message', 'N/A')
            # 限制消息长度
            if len(msg) > 300:
                msg = msg[:300] + "..."
            print(f"消息: {msg}")
            
            if result.get('data'):
                data = result['data']
                if isinstance(data, dict):
                    # 单个查询结果
                    if 'gift_id' in data:
                        print(f"  - 礼物ID: {data.get('gift_id')}")
                        print(f"  - 礼物名称: {data.get('gift_name', 'N/A')}")
                        print(f"  - 礼物类型: {data.get('gift_type', 'N/A')}")
                    # 批量查询结果
                    elif 'results' in data:
                        results = data['results']
                        print(f"  - 查询数量: {len(results)}")
                        for r in results[:3]:  # 只显示前3个
                            print(f"    • {r.get('gift_id')}: {r.get('gift_name', 'N/A')} ({r.get('gift_type', 'N/A')})")
                elif isinstance(data, list):
                    print(f"  - 查询数量: {len(data)}")
                    for item in data[:3]:  # 只显示前3个
                        if isinstance(item, dict):
                            print(f"    • {item.get('gift_id')}: {item.get('gift_name', 'N/A')}")
        else:
            print(f"❌ 失败")
            msg = result.get('message', 'N/A')
            # 限制消息长度
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
    print("开始批量执行礼物查询指令测试")
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
