#!/usr/bin/env python3
"""
执行 test_ml.md 中的所有测试指令
"""
import requests
import json
import time
import re
from typing import List, Dict, Tuple

API_URL = "http://localhost:8002/agent/execute"

def parse_test_ml(filepath: str = "test_ml.md") -> List[Dict]:
    """
    解析 test_ml.md 文件，提取所有测试指令
    
    Returns:
        List[Dict]: 每个字典包含 category 和 commands
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    test_cases = []
    current_section = None
    current_subsection = None
    current_commands = []
    
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        
        # 跳过空行和特殊标记
        if not line or line.startswith('#') and ('📋' in line or '💡' in line or '💎' in line or '📝' in line or '🔍' in line):
            continue
        
        # 匹配章节标题（## 一、二、三...）
        section_match = re.match(r'^##\s+([一二三四五六七八九十]+、.+)$', line)
        if section_match:
            # 保存之前的subsection
            if current_subsection and current_commands:
                test_cases.append({
                    "category": f"{current_section} - {current_subsection}",
                    "commands": current_commands.copy()
                })
                current_commands = []
            
            current_section = section_match.group(1)
            current_subsection = None
            continue
        
        # 匹配子章节标题（### 1.1, 2.1, etc.）
        subsection_match = re.match(r'^###\s+(.+)$', line)
        if subsection_match:
            # 保存之前的subsection
            if current_subsection and current_commands:
                test_cases.append({
                    "category": f"{current_section} - {current_subsection}",
                    "commands": current_commands.copy()
                })
                current_commands = []
            
            current_subsection = subsection_match.group(1)
            continue
        
        # 跳过说明性文本（包含特殊字符或以-开头）
        if line.startswith('-') or line.startswith('*') or line.startswith('>'):
            continue
        if '**' in line or line.startswith('（') or line.startswith('注：'):
            continue
        
        # 如果在一个subsection中，且不是空行，认为是指令
        if current_section and current_subsection and line:
            # 跳过纯数字或特殊格式的行
            if re.match(r'^\d+[\.\、]?\s*$', line):
                continue
            # 跳过包含特殊标记的行
            if any(marker in line for marker in ['---', '===', '```', '###', '##', '#']):
                continue
            
            current_commands.append(line)
    
    # 保存最后一个subsection
    if current_subsection and current_commands:
        test_cases.append({
            "category": f"{current_section} - {current_subsection}",
            "commands": current_commands.copy()
        })
    
    return test_cases


def execute_command(command: str, index: int, total: int) -> Dict:
    """执行单个指令"""
    print(f"\n{'='*80}")
    print(f"[{index}/{total}] 执行指令: {command}")
    print(f"{'='*80}")
    
    try:
        payload = {
            "business_code": "ear_test",
            "user_input": command,
            "context": {
                "operator": "test_ml_batch",
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
            if len(msg) > 150:
                msg = msg[:150] + "..."
            print(f"消息: {msg}")
            
            # 打印意图识别
            intent = result.get('intent', {})
            skill_name = intent.get('skill_name', result.get('skill_name', 'N/A'))
            print(f"Skill: {skill_name}")
        else:
            print(f"❌ 失败")
            msg = result.get('message', 'N/A')
            if len(msg) > 200:
                msg = msg[:200] + "..."
            print(f"消息: {msg}")
            
            # 打印意图识别
            intent = result.get('intent', {})
            skill_name = intent.get('skill_name', result.get('skill_name', 'N/A'))
            print(f"Skill: {skill_name}")
        
        return {
            "command": command,
            "success": result.get('success', False),
            "message": result.get('message', ''),
            "skill_name": result.get('skill_name') or intent.get('skill_name')
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
    print("开始执行 test_ml.md 中的所有测试指令")
    print("="*80)
    
    # 解析测试文件
    print("\n正在解析 test_ml.md...")
    test_cases = parse_test_ml()
    
    total_commands = sum(len(tc['commands']) for tc in test_cases)
    print(f"共找到 {len(test_cases)} 个测试分类，{total_commands} 条测试指令\n")
    
    # 执行测试
    all_results = []
    current_index = 0
    
    for test_case in test_cases:
        category = test_case['category']
        commands = test_case['commands']
        
        if not commands:
            continue
        
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
    
    # 打印汇总报告
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
        
        # 只显示失败的指令
        failed_commands = [r for r in results if not r['success']]
        if failed_commands:
            print(f"  失败指令:")
            for r in failed_commands:
                cmd_short = r['command'][:60] + "..." if len(r['command']) > 60 else r['command']
                print(f"    ❌ {cmd_short}")
    
    print(f"\n{'='*80}")
    print(f"总计: 成功 {total_success}, 失败 {total_fail}, 总数 {total_success + total_fail}")
    success_rate = (total_success / (total_success + total_fail) * 100) if (total_success + total_fail) > 0 else 0
    print(f"成功率: {success_rate:.1f}%")
    print(f"{'='*80}\n")
    
    # 保存详细结果到JSON文件
    output_file = "test_ml_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            "summary": {
                "total": total_success + total_fail,
                "success": total_success,
                "fail": total_fail,
                "success_rate": f"{success_rate:.1f}%"
            },
            "details": all_results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"详细结果已保存到: {output_file}\n")


if __name__ == "__main__":
    main()
