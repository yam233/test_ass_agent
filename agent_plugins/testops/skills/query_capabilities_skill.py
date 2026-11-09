"""
查询系统能力技能
返回系统当前具备的所有业务功能
"""
from typing import Dict, Any
from agent_core.protocol import SkillInput, SkillOutput
from .base_mcp_skill import BaseMCPSkill


class QueryCapabilitiesSkill(BaseMCPSkill):
    """查询系统能力技能"""
    
    def execute(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行能力查询
        
        Args:
            skill_input: Skill输入协议
            
        Returns:
            SkillOutput: 包含系统能力列表
        """
        capabilities = {
            "success": True,
            "message": "系统能力列表",
            "data": {
                "categories": [
                    {
                        "category": "用户管理",
                        "description": "用户信息查询和验证码管理",
                        "capabilities": [
                            {
                                "name": "查询用户信息",
                                "description": "支持通过用户ID、直播间ID、邮箱、手机号查询用户信息",
                                "examples": [
                                    "查询用户9075566的信息",
                                    "查询直播间123456的用户信息",
                                    "查询邮箱user@example.com的用户",
                                    "查询手机号15000000490的用户"
                                ]
                            },
                            {
                                "name": "获取验证码",
                                "description": "支持通过手机号、用户ID、邮箱查询验证码",
                                "examples": [
                                    "获取手机号15000000490的验证码",
                                    "查询用户9075566的验证码",
                                    "获取邮箱user@example.com的验证码"
                                ]
                            }
                        ]
                    },
                    {
                        "category": "礼物管理",
                        "description": "礼物发放、查询等操作",
                        "capabilities": [
                            {
                                "name": "发放专属礼物",
                                "description": "支持发放用户专属礼物（2开头）、直播间专属礼物（7开头）、随机礼物（8开头）",
                                "examples": [
                                    "给用户9075566发礼物20123到专属tab",
                                    "给直播间123456发放礼物70001",
                                    "发放随机礼物80103"
                                ]
                            },
                            {
                                "name": "发放背包礼物",
                                "description": "统一使用“发礼物到背包”指令：免费礼物（3开头）走Grafana后台，白给礼物（4开头）走DB插入",
                                "examples": [
                                    "给用户9075566发10个礼物301到背包",
                                    "给用户9075566发放背包礼物40109，数量5"
                                ]
                            },
                            {
                                "name": "查询礼物信息",
                                "description": "查询礼物详细信息，支持按ID或名称查询",
                                "examples": [
                                    "查询礼物80103的信息",
                                    "查询礼物猫粮"
                                ]
                            },
                            {
                                "name": "查询礼物记录",
                                "description": "查询用户或直播间的专属礼物发放记录",
                                "examples": [
                                    "查询用户9075566的礼物记录",
                                    "查询直播间123456的专属礼物"
                                ]
                            },
                            {
                                "name": "检查礼物类型",
                                "description": "检查礼物类型和发放规则",
                                "examples": [
                                    "检查礼物20123的类型",
                                    "礼物80103是什么类型"
                                ]
                            },
                            {
                                "name": "列出礼物类型规则",
                                "description": "列出所有礼物类型及其发放规则",
                                "examples": [
                                    "列出所有礼物类型",
                                    "礼物类型有哪些"
                                ]
                            }
                        ]
                    },
                    {
                        "category": "奖池管理",
                        "description": "奖池配置查询和权重调整",
                        "capabilities": [
                            {
                                "name": "查询奖池配置",
                                "description": "支持通过礼物ID或奖池ID查询奖池配置",
                                "examples": [
                                    "查询礼物80103的奖池配置",
                                    "查询奖池257的配置"
                                ]
                            },
                            {
                                "name": "修改礼物权重为最大",
                                "description": "将奖池中某个礼物的权重改为最大（乘以1000000）",
                                "examples": [
                                    "将奖池257中礼物91384的权重改为最大",
                                    "修改奖池257礼物91384权重为最大"
                                ]
                            },
                            {
                                "name": "修改大奖权重为0",
                                "description": "将奖池中保底大奖的权重改为0",
                                "examples": [
                                    "将奖池257中大奖91376的权重改为0",
                                    "修改奖池257大奖91376权重为0"
                                ]
                            },
                            {
                                "name": "验证随机礼物奖池",
                                "description": "验证随机礼物和对应奖池礼物的图片和动效",
                                "examples": [
                                    "验证随机礼物80103的奖池礼物"
                                ]
                            }
                        ]
                    },
                    {
                        "category": "配置检查",
                        "description": "外观和奖励配置查询",
                        "capabilities": [
                            {
                                "name": "查询外观配置",
                                "description": "查询外观资源配置和有效期（支持单个和批量查询）",
                                "examples": [
                                    "查询外观50811的配置",
                                    "外观50811是否已配置",
                                    "批量查询外观40667,40789"
                                ]
                            },
                            {
                                "name": "查询奖励配置",
                                "description": "查询奖励配置的有效期和最大有效期（支持单个和批量查询）",
                                "examples": [
                                    "查询奖励3的配置",
                                    "查询礼物30002的奖励配置",
                                    "查询活动id 1480的奖励信息"
                                ]
                            }
                        ]
                    },
                    {
                        "category": "外观管理",
                        "description": "外观发放到外观中心平台",
                        "capabilities": [
                            {
                                "name": "发放外观到平台",
                                "description": "通过 Grafana 后台 API 发放外观到外观中心平台，支持批量发放",
                                "examples": [
                                    "给用户9075566发放外观70244，有效期7天",
                                    "给用户9075566，9075567发放外观70244，永久有效",
                                    "批量发放外观70244给用户9075566、9075567、9075568"
                                ]
                            }
                        ]
                    },
                    {
                        "category": "背包礼物管理",
                        "description": "通过Grafana后台发放和清空背包礼物",
                        "capabilities": [
                            {
                                "name": "Grafana发放背包礼物",
                                "description": "通过 Grafana 后台 API 发放背包礼物（仅支持3开头），支持批量发放和数量设置",
                                "examples": [
                                    "给用户9075566发放背包礼物301，数量10",
                                    "给用户9075566，9075567发放背包礼物301，数量5，有效期30天",
                                    "通过Grafana发放背包礼物30109给用户9075566，数量1，永久有效"
                                ]
                            },
                            {
                                "name": "清空背包礼物",
                                "description": "通过 Grafana 后台 API 清空用户背包中的免费礼物（仅支持3开头），支持批量清空",
                                "examples": [
                                    "清空用户9075566的背包礼物301",
                                    "清空用户9075566，9075567的背包礼物301",
                                    "批量清空用户背包礼物301"
                                ]
                            }
                        ]
                    },
                    {
                        "category": "后台功能查询",
                        "description": "查询后台配置地址和功能清单",
                        "capabilities": [
                            {
                                "name": "查询后台URL",
                                "description": "搜索Grafana/Mongo后台功能URL",
                                "examples": [
                                    "查询随机礼物后台地址",
                                    "查询外观配置URL",
                                    "查询奖池配置地址"
                                ]
                            },
                            {
                                "name": "列出功能清单",
                                "description": "列出所有后台功能清单",
                                "examples": [
                                    "列出所有功能",
                                    "列出grafana功能"
                                ]
                            },
                            {
                                "name": "查询枚举值",
                                "description": "获取系统枚举值（如外观类型）",
                                "examples": [
                                    "查询外观类型枚举"
                                ]
                            }
                        ]
                    },
                    {
                        "category": "钻石充值",
                        "description": "钻石发放功能（Mock实现）",
                        "capabilities": [
                            {
                                "name": "发放钻石",
                                "description": "支持通过用户ID或手机号发放钻石（当前为Mock实现）",
                                "examples": [
                                    "给用户9075566发500万钻石",
                                    "给手机号15000000490充值200万钻石"
                                ],
                                "note": "⚠️ 当前为Mock实现，不会真实操作数据库"
                            }
                        ]
                    },
                    {
                        "category": "脚本执行",
                        "description": "执行testops_test项目脚本",
                        "capabilities": [
                            {
                                "name": "执行脚本",
                                "description": "执行testops_test项目的测试脚本",
                                "examples": [
                                    "执行脚本live/draw01.py"
                                ]
                            }
                        ]
                    }
                ],
                "statistics": {
                    "total_categories": 9,
                    "total_capabilities": 22,
                    "implementation_status": {
                        "fully_implemented": 21,
                        "mock_implementation": 1
                    }
                }
            }
        }
        
        # 格式化友好的消息（简洁版）
        message_lines = ["✅ AI测试助手能力清单\n"]
        
        categories = capabilities["data"]["categories"]
        for category_info in categories:
            category = category_info["category"]
            caps = category_info["capabilities"]
            
            message_lines.append(f"【{category}】")
            for cap in caps:
                name = cap["name"]
                examples = cap.get("examples", [])
                
                # 只显示能力名称和第一个示例
                if examples:
                    message_lines.append(f"• {name}：{examples[0]}")
                else:
                    message_lines.append(f"• {name}")
            message_lines.append("")  # 空行分隔
        
        # 添加统计信息
        stats = capabilities["data"]["statistics"]
        message_lines.append(f"📊 共 {stats['total_categories']} 类功能，{stats['total_capabilities']} 项能力")
        
        friendly_message = "\n".join(message_lines)
        
        return SkillOutput(
            code=0,
            msg=friendly_message,
            data={}  # 不返回原始数据，避免重复显示
        )
