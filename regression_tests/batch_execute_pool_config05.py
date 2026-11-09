#!/usr/bin/env python3
"""
批量执行奖池配置管理指令
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 所有测试指令
test_cases = [
    {
        "category": "5.1 通过礼物ID查询",
        "commands": [
            "查询礼物80103的奖池配置",
            "查询奖池257的配置"
        ]
    },
    {
        "category": "5.2 将礼物权重改为最大值",
        "commands": [
            "将奖池257中礼物91384的权重改为最大值",
            "将奖池257中大奖91376的权重改为0"
        ]
    },
    {
        "category": "5.3 异常场景",
        "commands": [
            "将奖池999中礼物91384的权重改为最大值",
            "将奖池257中礼物99999的权重改为最大值",
            "查询奖池配置",
            "查询礼物的奖池配置"
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
                    # 奖池配置查询结果
                    if 'pool_id' in data:
                        print(f"  - 奖池ID: {data.get('pool_id')}")
                    if 'pool_name' in data:
                        print(f"  - 奖池名称: {data.get('pool_name')}")
                    if 'gift_id' in data:
                        print(f"  - 礼物ID: {data.get('gift_id')}")
                    if 'total_gifts' in data:
                        print(f"  - 礼物总数: {data.get('total_gifts')}")
                    if 'prizes' in data:
                        prizes = data['prizes']
                        if isinstance(prizes, list) and len(prizes) > 0:
                            print(f"  - 奖品数量: {len(prizes)}")
                    
                    # 权重修改结果
                    if 'old_weight' in data:
                        print(f"  - 原权重: {data.get('old_weight')}")
                    if 'new_weight' in data:
                        print(f"  - 新权重: {data.get('new_weight')}")
                    if 'updated' in data:
                        print(f"  - 更新状态: {data.get('updated')}")
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
    print("开始批量执行奖池配置管理指令测试")
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
