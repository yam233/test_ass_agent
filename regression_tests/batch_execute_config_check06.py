#!/usr/bin/env python3
"""
批量执行配置核验指令
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 所有测试指令
test_cases = [
    {
        "category": "6.1 查询外观/礼物/奖励配置",
        "commands": [
            "查询外观50811的有效期和最大有效期",
            "查询外观40597的配置",
            "查询礼物20475的有效期和最大有效期",
            "查询奖励148001的配置",
            "查询奖励ID 148001 的有效期"
        ]
    },
    {
        "category": "6.2 查询活动奖励配置",
        "commands": [
            "查询活动1480的奖励配置",
            "查询奖励信息，活动id:1480"
        ]
    },
    {
        "category": "6.3 批量查询",
        "commands": [
            "查询外观50811、40736、10281的配置",
            "查询多个外观的有效期",
            "查询礼物20478、20475、20515的奖励配置",
            "活动id:1480 查询礼物 20478、20475、20515、20514的奖励配置"
        ]
    },
    {
        "category": "6.4 异常场景",
        "commands": [
            "查询外观20478的有效期和最大有效期",
            "查询礼物999999的有效期",
            "查询活动9999的奖励配置",
            "查询奖励配置"
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
                    # 外观配置
                    if 'appearance_id' in data:
                        print(f"  - 外观ID: {data.get('appearance_id')}")
                    if 'appearance_name' in data:
                        print(f"  - 外观名称: {data.get('appearance_name')}")
                    if 'validity_days' in data:
                        print(f"  - 有效期: {data.get('validity_days')}天")
                    if 'max_validity_days' in data:
                        print(f"  - 最大有效期: {data.get('max_validity_days')}天")
                    
                    # 礼物配置
                    if 'gift_id' in data and 'appearance_id' not in data:
                        print(f"  - 礼物ID: {data.get('gift_id')}")
                    if 'gift_name' in data:
                        print(f"  - 礼物名称: {data.get('gift_name')}")
                    
                    # 奖励配置
                    if 'reward_id' in data:
                        print(f"  - 奖励ID: {data.get('reward_id')}")
                    if 'activity_id' in data:
                        print(f"  - 活动ID: {data.get('activity_id')}")
                    if 'reward_type' in data:
                        print(f"  - 奖励类型: {data.get('reward_type')}")
                    
                    # 批量查询结果
                    if 'results' in data:
                        results = data['results']
                        if isinstance(results, list):
                            print(f"  - 查询数量: {len(results)}")
                            success_count = sum(1 for r in results if r.get('success'))
                            print(f"  - 成功: {success_count}/{len(results)}")
                    
                    # 配置数量
                    if 'total' in data:
                        print(f"  - 总数: {data.get('total')}")
        else:
            print(f"❌ 失败")
            msg = result.get('message', 'N/A')
            # 只打印前300个字符
            if len(msg) > 300:
                msg = msg[:300] + "..."
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
    print("开始批量执行配置核验指令测试")
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
