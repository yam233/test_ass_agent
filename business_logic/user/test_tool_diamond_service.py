"""
使用测试工具平台充值钻石
"""
import requests
import logging
import json
import os
from typing import Optional
from business_logic.user.user_service import query_user_info
from business_logic.common.db import check_user_exists
from utils.message_formatter import MessageFormatter

logger = logging.getLogger(__name__)

# 加载配置
def load_test_tool_config():
    """加载测试工具配置"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "config/business/testops/test_tool_config.json"
    )
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get("test_tool", {})
    except Exception as e:
        logger.warning(f"加载测试工具配置失败: {e}，使用默认配置")
        return {
            "base_url": "https://internal.example.invalid",
            "endpoints": {"top_up": "/top_up"},
            "auth": {
                "sid": "VjjAYA0oQ0voNZHgAAFj",
                "cookies": {
                    "uid": "23978",
                    "username": "yuanyu",
                    "session": "eyJfcGVybWFuZW50Ijp0cnVlLCJzZXNzaW9uX2lkIjoiZjcyYzVhN2YxOWMxMzUzNjllNTU2ZDUxYTVhMTg1YWQiLCJ1c2VybmFtZSI6Inl1YW55dSJ9.aZdBBg.TnFpYkTk5b07nquDanGOLhTsKbM"
                }
            },
            "headers": {
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
            "diamond_limits": {"max_wan": 10000}
        }

TEST_TOOL_CONFIG = load_test_tool_config()


def top_up_diamond_via_test_tool(
    user_id: Optional[int] = None, 
    phone: Optional[str] = None,
    email: Optional[str] = None,
    total_diamond_wan: int = 100
):
    """
    通过测试工具平台充值钻石
    
    充值规则：
    - diamond=1: 每次充值100万
    - diamond=2: 每次充值1000万
    - diamond=3: 每次充值1亿
    
    示例：
    - 充值100万：diamond=1，执行1次
    - 充值200万：diamond=1，执行2次
    - 充值1000万：diamond=2，执行1次
    - 充值1亿：diamond=3，执行1次
    - 超过1亿：不支持
    
    策略：优先使用最大档位，剩余部分使用较小档位
    
    Args:
        user_id: 用户ID（可选）
        phone: 手机号（可选）
        email: 邮箱（可选）
        total_diamond_wan: 总充值金额（单位：万）
        
    Returns:
        充值结果
    """
    
    # 1. 参数校验 - 用户信息
    if not user_id and not phone and not email:
        return {
            "success": False,
            "message": MessageFormatter.missing_param_error(
                param_name="用户信息",
                param_description="用户信息（user_id、phone 或 email）",
                examples=[
                    "给用户9075566发300万钻石",
                    "给手机号15000000490充值300万钻石",
                    "给邮箱live@testops.cn充值300万钻石"
                ]
            ),
            "data": None
        }
    
    # 1.5 参数校验 - 钻石数量必须明确指定
    if not total_diamond_wan or total_diamond_wan <= 0:
        return {
            "success": False,
            "message": MessageFormatter.missing_param_error(
                param_name="钻石数量",
                param_description="钻石数量（必须明确指定）",
                examples=[
                    "给用户9075566充值200万钻石",
                    "给用户9075566发300万钻石",
                    "给手机号15000000490充值1000万钻石"
                ]
            ),
            "data": None
        }
    
    # 2. 如果提供了手机号或邮箱，先查询用户ID
    if (phone or email) and not user_id:
        identifier = phone or email
        print(f"📱 查询{'手机号' if phone else '邮箱'} {identifier} 对应的用户...")
        user_result = query_user_info(phone=phone, email=email)
        
        if not user_result.get("success"):
            return {
                "success": False,
                "message": f"❌ {'手机号' if phone else '邮箱'} {identifier} 对应的用户不存在",
                "data": {
                    "phone": phone,
                    "email": email,
                    "user_id": None
                }
            }
        
        user_data = user_result.get("data", {})
        user_id = user_data.get("user_id")
        
        if not user_id:
            return {
                "success": False,
                "message": f"❌ 无法获取{'手机号' if phone else '邮箱'} {identifier} 对应的用户ID",
                "data": {
                    "phone": phone,
                    "email": email,
                    "user_id": None
                }
            }
        
        print(f"✅ 找到用户ID: {user_id}\n")
    
    # 3. 校验用户是否存在
    if not check_user_exists(user_id):
        return {
            "success": False,
            "message": f"❌ 用户ID {user_id} 不存在",
            "data": {
                "user_id": user_id,
                "phone": phone,
                "email": email
            }
        }
    
    
    # 4. 检查是否超过限制
    max_wan = TEST_TOOL_CONFIG.get("diamond_limits", {}).get("max_wan", 10000)
    if total_diamond_wan > max_wan:
        return {
            "success": False,
            "message": f"❌ 暂不支持超过{max_wan}万钻石的充值（{max_wan/10000}亿），当前请求: {total_diamond_wan}万",
            "data": {
                "user_id": user_id,
                "phone": phone,
                "email": email,
                "requested_diamond_wan": total_diamond_wan,
                "max_supported_wan": max_wan
            }
        }
    
    # 5. 准备请求配置
    base_url = TEST_TOOL_CONFIG.get("base_url", "https://internal.example.invalid")
    endpoint = TEST_TOOL_CONFIG.get("endpoints", {}).get("top_up", "/top_up")
    url = f"{base_url}{endpoint}"
    
    # 从配置读取认证信息
    auth_config = TEST_TOOL_CONFIG.get("auth", {})
    sid = auth_config.get("sid", "VjjAYA0oQ0voNZHgAAFj")
    cookies = auth_config.get("cookies", {})
    
    # 设置请求头
    headers = TEST_TOOL_CONFIG.get("headers", {})
    headers.update({
        'origin': base_url,
        'referer': f'{base_url}/top_up'
    })
    
    # 6. 计算充值策略
    # diamond=3: 1亿/次, diamond=2: 1000万/次, diamond=1: 100万/次
    count_1yi = total_diamond_wan // 10000  # 1亿的次数
    remaining = total_diamond_wan % 10000
    count_1000w = remaining // 1000  # 1000万的次数
    count_100w = (remaining % 1000) // 100  # 100万的次数
    
    total_rounds = count_1yi + count_1000w + count_100w
    
    print(f"💎 开始充值钻石")
    print("=" * 80)
    print(f"👤 用户ID: {user_id}")
    if phone:
        print(f"📱 手机号: {phone}")
    if email:
        print(f"📧 邮箱: {email}")
    print(f"💰 总金额: {total_diamond_wan:,}万钻石 ({total_diamond_wan * 10000:,}钻石)")
    print(f"📋 充值策略:")
    if count_1yi > 0:
        print(f"   • diamond=3 (1亿) × {count_1yi} 次")
    if count_1000w > 0:
        print(f"   • diamond=2 (1000万) × {count_1000w} 次")
    if count_100w > 0:
        print(f"   • diamond=1 (100万) × {count_100w} 次")
    print(f"🔄 总次数: {total_rounds} 次")
    print("=" * 80)
    
    success_count = 0
    failed_count = 0
    results = []
    current_round = 0
    
    # 先充值1亿的部分
    for i in range(count_1yi):
        current_round += 1
        try:
            data = {
                'userId': str(user_id),
                'sid': sid,
                'diamond': '3',  # 1亿
                'type': '0'
            }
            
            print(f"\n💎 第 {current_round}/{total_rounds} 次充值 (1亿)...")
            
            response = requests.post(url, headers=headers, cookies=cookies, data=data, verify=False)
            
            if response.status_code == 200:
                # 尝试解析JSON响应
                try:
                    json_response = response.json()
                    if json_response.get('success') == True:
                        success_count += 1
                        print(f"   ✅ 充值成功！已到账 100,000,000 钻石")
                        results.append({
                            "round": current_round,
                            "success": True,
                            "amount": 100000000,
                            "diamond_param": 3,
                            "message": "充值成功"
                        })
                    else:
                        failed_count += 1
                        print(f"   ❌ 充值失败: {response.text[:100]}")
                        results.append({
                            "round": current_round,
                            "success": False,
                            "amount": 0,
                            "diamond_param": 3,
                            "message": response.text[:100]
                        })
                except:
                    # 如果不是JSON，按原来的方式判断
                    if response.text == 'success' or '成功' in response.text:
                        success_count += 1
                        print(f"   ✅ 充值成功！已到账 100,000,000 钻石")
                        results.append({
                            "round": current_round,
                            "success": True,
                            "amount": 100000000,
                            "diamond_param": 3,
                            "message": "充值成功"
                        })
                    else:
                        failed_count += 1
                        print(f"   ❌ 充值失败: {response.text[:100]}")
                        results.append({
                            "round": current_round,
                            "success": False,
                            "amount": 0,
                            "diamond_param": 3,
                            "message": response.text[:100]
                        })
            else:
                failed_count += 1
                print(f"   ❌ 请求失败: HTTP {response.status_code}")
                results.append({
                    "round": current_round,
                    "success": False,
                    "amount": 0,
                    "diamond_param": 3,
                    "message": f"HTTP {response.status_code}"
                })
                
        except Exception as e:
            failed_count += 1
            print(f"   ❌ 充值异常: {e}")
            results.append({
                "round": current_round,
                "success": False,
                "amount": 0,
                "diamond_param": 3,
                "message": str(e)
            })
    
    # 再充值1000万的部分
    for i in range(count_1000w):
        current_round += 1
        try:
            data = {
                'userId': str(user_id),
                'sid': sid,
                'diamond': '2',  # 1000万
                'type': '0'
            }
            
            print(f"\n💎 第 {current_round}/{total_rounds} 次充值 (1000万)...")
            
            response = requests.post(url, headers=headers, cookies=cookies, data=data, verify=False)
            
            if response.status_code == 200:
                # 尝试解析JSON响应
                try:
                    json_response = response.json()
                    if json_response.get('success') == True:
                        success_count += 1
                        print(f"   ✅ 充值成功！已到账 10,000,000 钻石")
                        results.append({
                            "round": current_round,
                            "success": True,
                            "amount": 10000000,
                            "diamond_param": 2,
                            "message": "充值成功"
                        })
                    else:
                        failed_count += 1
                        print(f"   ❌ 充值失败: {response.text[:100]}")
                        results.append({
                            "round": current_round,
                            "success": False,
                            "amount": 0,
                            "diamond_param": 2,
                            "message": response.text[:100]
                        })
                except:
                    # 如果不是JSON，按原来的方式判断
                    if response.text == 'success' or '成功' in response.text:
                        success_count += 1
                        print(f"   ✅ 充值成功！已到账 10,000,000 钻石")
                        results.append({
                            "round": current_round,
                            "success": True,
                            "amount": 10000000,
                            "diamond_param": 2,
                            "message": "充值成功"
                        })
                    else:
                        failed_count += 1
                        print(f"   ❌ 充值失败: {response.text[:100]}")
                        results.append({
                            "round": current_round,
                            "success": False,
                            "amount": 0,
                            "diamond_param": 2,
                            "message": response.text[:100]
                        })
            else:
                failed_count += 1
                print(f"   ❌ 请求失败: HTTP {response.status_code}")
                results.append({
                    "round": current_round,
                    "success": False,
                    "amount": 0,
                    "diamond_param": 2,
                    "message": f"HTTP {response.status_code}"
                })
                
        except Exception as e:
            failed_count += 1
            print(f"   ❌ 充值异常: {e}")
            results.append({
                "round": current_round,
                "success": False,
                "amount": 0,
                "diamond_param": 2,
                "message": str(e)
            })
    
    # 再充值100万的部分
    for i in range(count_100w):
        current_round += 1
        try:
            data = {
                'userId': str(user_id),
                'sid': sid,
                'diamond': '1',  # 100万
                'type': '0'
            }
            
            print(f"\n💎 第 {current_round}/{total_rounds} 次充值 (100万)...")
            
            response = requests.post(url, headers=headers, cookies=cookies, data=data, verify=False)
            
            if response.status_code == 200:
                # 尝试解析JSON响应
                try:
                    json_response = response.json()
                    if json_response.get('success') == True:
                        success_count += 1
                        print(f"   ✅ 充值成功！已到账 1,000,000 钻石")
                        results.append({
                            "round": current_round,
                            "success": True,
                            "amount": 1000000,
                            "diamond_param": 1,
                            "message": "充值成功"
                        })
                    else:
                        failed_count += 1
                        print(f"   ❌ 充值失败: {response.text[:100]}")
                        results.append({
                            "round": current_round,
                            "success": False,
                            "amount": 0,
                            "diamond_param": 1,
                            "message": response.text[:100]
                        })
                except:
                    # 如果不是JSON，按原来的方式判断
                    if response.text == 'success' or '成功' in response.text:
                        success_count += 1
                        print(f"   ✅ 充值成功！已到账 1,000,000 钻石")
                        results.append({
                            "round": current_round,
                            "success": True,
                            "amount": 1000000,
                            "diamond_param": 1,
                            "message": "充值成功"
                        })
                    else:
                        failed_count += 1
                        print(f"   ❌ 充值失败: {response.text[:100]}")
                        results.append({
                            "round": current_round,
                            "success": False,
                            "amount": 0,
                            "diamond_param": 1,
                            "message": response.text[:100]
                        })
            else:
                failed_count += 1
                print(f"   ❌ 请求失败: HTTP {response.status_code}")
                results.append({
                    "round": current_round,
                    "success": False,
                    "amount": 0,
                    "diamond_param": 1,
                    "message": f"HTTP {response.status_code}"
                })
                
        except Exception as e:
            failed_count += 1
            print(f"   ❌ 充值异常: {e}")
            results.append({
                "round": current_round,
                "success": False,
                "amount": 0,
                "diamond_param": 1,
                "message": str(e)
            })
    
    # 计算实际充值金额
    actual_diamond = sum(r['amount'] for r in results if r['success'])
    
    # 汇总结果
    print("\n" + "=" * 80)
    print("💎 充值完成")
    print("=" * 80)
    print(f"✅ 成功: {success_count} 次")
    print(f"❌ 失败: {failed_count} 次")
    print(f"💰 实际到账: {actual_diamond:,} 钻石 ({actual_diamond / 10000}万)")
    if phone or email:
        print(f"👤 用户ID: {user_id}")
    if phone:
        print(f"📱 手机号: {phone}")
    if email:
        print(f"📧 邮箱: {email}")
    print("=" * 80)
    
    # 生成友好的消息
    details = {
        "👤 用户ID": user_id,
        "💰 到账金额": f"{actual_diamond:,} 钻石（{actual_diamond / 10000}万）",
        "📊 充值详情": f"分{total_rounds}次充值，成功{success_count}次，失败{failed_count}次"
    }
    
    if phone:
        details["📱 手机号"] = phone
    if email:
        details["📧 邮箱"] = email
    
    suggestions = [
        f"查询用户{user_id}的信息（验证余额）",
        f"给用户{user_id}发礼物到背包"
    ]
    
    if failed_count == 0:
        message = MessageFormatter.success_with_details(
            success_message="充值完成",
            details=details,
            suggestions=suggestions
        )
    else:
        message = MessageFormatter.operation_result(
            operation_name="充值",
            success_count=success_count,
            fail_count=failed_count,
            details=details
        )
    
    return {
        "success": failed_count == 0,
        "message": message,
        "data": {
            "user_id": user_id,
            "phone": phone,
            "email": email,
            "requested_diamond_wan": total_diamond_wan,
            "actual_diamond": actual_diamond,
            "total_rounds": total_rounds,
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }
    }


if __name__ == "__main__":
    # 测试
    import urllib3
    urllib3.disable_warnings()
    
    # 测试充值1000万
    result = top_up_diamond_via_test_tool(
        user_id=9075566,
        total_diamond_wan=1000  # 1000万钻石
    )
    
    print("\n最终结果:")
    print(result)
