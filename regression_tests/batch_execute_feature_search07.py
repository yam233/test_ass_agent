#!/usr/bin/env python3
"""
批量执行功能搜索指令
"""
import requests
import json
import time

API_URL = "http://localhost:8002/agent/execute"

# 所有测试指令
test_cases = [
    {
        "category": "7.1 搜索所有数据源",
        "commands": [
            "查询随机礼物地址",
            "查询随机礼物配置地址",
            "查询外观配置URL",
            "查询外观配置后台",
            "查询外观资源状态",
            "查询魔方配置地址",
            "查询礼物url",
            "查询外观配置grafana地址",
            "查询奖池mongo地址",
            "查询礼物mongo地址",
            "查询用户mongo",
            "查询礼物配置"
        ]
    },
    {
        "category": "7.2 异常场景",
        "commands": [
            "查询URL",
            "查询地址"
        ]
    },
    {
        "category": "7.3 列出功能清单",
        "commands": [
            "列出所有功能",
            "查看功能列表",
            "列出grafana功能",
            "列出所有后台功能"
        ]
    },
    {
        "category": "7.4 获取枚举定义",
        "commands": [
            "查询外观类型枚举",
            "查询枚举appearance_type",
            "查看外观类型列表",
            "查询外观类型列表"
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
            msg = result.get('message', 'N/A')
            # 限制消息长度
            if len(msg) > 200:
                msg = msg[:200] + "..."
            print(f"消息: {msg}")
            
            if result.get('data'):
                data = result['data']
                if isinstance(data, dict):
                    # 搜索结果
                    if 'results' in data:
                        results = data['results']
                        print(f"  - 找到 {len(results)} 个结果")
                        for r in results[:2]:  # 只显示前2个
                            print(f"    • {r.get('title', 'N/A')}")
                    # 功能列表
                    elif 'features' in data:
                        features = data['features']
                        print(f"  - 功能数量: {len(features)}")
                    # 枚举值
                    elif 'enums' in data or 'values' in data:
                        print(f"  - 枚举值已返回")
                elif isinstance(data, list):
                    print(f"  - 返回 {len(data)} 项")
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
    print("开始批量执行功能搜索指令测试")
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
