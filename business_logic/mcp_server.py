#!/usr/bin/env python3
"""
本地 MCP 服务器
使用 business_logic 模块中的业务逻辑
参考 MaoerProject 的实现方式，但代码在本项目中
"""
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import uvicorn

# 导入业务逻辑
from business_logic import query_user_info, query_verify_code

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Ear Test Agent - Local MCP Server",
    version="1.0.0",
    description="本地 MCP 服务器，业务逻辑在本项目中实现"
)


class ToolCallRequest(BaseModel):
    """工具调用请求"""
    name: str
    arguments: Dict[str, Any]
    env: Optional[str] = "uat"


class ToolCallResponse(BaseModel):
    """工具调用响应"""
    content: List[Dict[str, Any]]


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Ear Test Agent - Local MCP Server",
        "version": "1.0.0",
        "description": "本地 MCP 服务器，业务逻辑在本项目中实现",
        "endpoints": {
            "GET /": "服务信息",
            "GET /tools/list": "列出所有可用工具",
            "POST /tools/call": "调用工具",
            "GET /health": "健康检查"
        }
    }


@app.get("/tools/list")
async def list_tools():
    """列出所有可用工具"""
    return {
        "tools": [
            {
                "name": "query_user_info",
                "description": "查询用户信息（支持通过用户ID、直播间ID、邮箱、手机号查询）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "integer",
                            "description": "用户ID"
                        },
                        "room_id": {
                            "type": "integer",
                            "description": "直播间ID"
                        },
                        "email": {
                            "type": "string",
                            "description": "邮箱地址"
                        },
                        "phone": {
                            "type": "string",
                            "description": "手机号"
                        }
                    }
                }
            },
            {
                "name": "get_verify_code",
                "description": "获取验证码（支持通过手机号、用户ID、邮箱查询）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "phone": {
                            "type": "string",
                            "description": "手机号"
                        },
                        "user_id": {
                            "type": "integer",
                            "description": "用户ID"
                        },
                        "email": {
                            "type": "string",
                            "description": "邮箱地址"
                        }
                    }
                }
            },
            {
                "name": "add_gift_to_exclusive_tab",
                "description": "发放礼物到专属tab（支持用户专属礼物、直播间专属礼物、随机礼物）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gift_id": {
                            "type": "integer",
                            "description": "礼物ID"
                        },
                        "user_id": {
                            "type": "integer",
                            "description": "用户ID（用户专属礼物必填）"
                        },
                        "room_id": {
                            "type": "integer",
                            "description": "直播间ID（直播间专属礼物必填）"
                        },
                        "duration_days": {
                            "type": "integer",
                            "description": "有效期天数，默认7天，0表示永久",
                            "default": 7
                        }
                    },
                    "required": ["gift_id"]
                }
            },
            {
                "name": "add_gift_to_backpack",
                "description": "发放礼物到背包（仅支持免费礼物和白给礼物）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gift_id": {
                            "type": "integer",
                            "description": "礼物ID（仅免费/白给）"
                        },
                        "user_id": {
                            "type": "integer",
                            "description": "用户ID"
                        },
                        "num": {
                            "type": "integer",
                            "description": "数量，默认1",
                            "default": 1
                        },
                        "duration_days": {
                            "type": "integer",
                            "description": "有效期天数，0=永久，默认7天",
                            "default": 7
                        }
                    },
                    "required": ["gift_id", "user_id"]
                }
            },
            {
                "name": "query_gift_records",
                "description": "查询礼物发放记录",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "element_id": {
                            "type": "integer",
                            "description": "用户ID 或 直播间ID"
                        },
                        "custom_type": {
                            "type": "integer",
                            "description": "类型筛选: 2=直播间专属, 3=用户专属"
                        }
                    },
                    "required": ["element_id"]
                }
            },
            {
                "name": "check_gift_type",
                "description": "检查礼物类型和发放规则",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gift_id": {
                            "type": "integer",
                            "description": "礼物ID"
                        }
                    },
                    "required": ["gift_id"]
                }
            },
            {
                "name": "query_pool_config",
                "description": "查询奖池配置（支持通过礼物ID或奖池ID查询）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gift_id": {
                            "type": "integer",
                            "description": "礼物ID（与pool_id二选一）"
                        },
                        "pool_id": {
                            "type": ["integer", "string"],
                            "description": "奖池ID（与gift_id二选一）"
                        }
                    }
                }
            },
            {
                "name": "query_gifts_by_name",
                "description": "根据礼物名称模糊查询礼物信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gift_name": {
                            "type": "string",
                            "description": "礼物名称（支持模糊匹配）"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回的结果数量，默认10",
                            "default": 10
                        }
                    },
                    "required": ["gift_name"]
                }
            },
            {
                "name": "query_gift_info",
                "description": "查询礼物信息（支持按ID、批量ID或名称模糊查询MongoDB）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gift_id": {
                            "type": "integer",
                            "description": "礼物ID（可选，精确查询单个礼物）"
                        },
                        "gift_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "礼物ID列表（可选，批量查询多个礼物）"
                        },
                        "gift_name": {
                            "type": "string",
                            "description": "礼物名称（可选，模糊查询）"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回的结果数量（名称查询时使用），默认10",
                            "default": 10
                        }
                    }
                }
            },
            {
                "name": "list_gift_types",
                "description": "列出所有礼物类型规则",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "update_pool_gift_weight_to_max",
                "description": "将奖池中某个礼物的权重改为最大（乘以1000000）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pool_id": {
                            "type": "integer",
                            "description": "奖池ID"
                        },
                        "gift_id": {
                            "type": "integer",
                            "description": "礼物ID"
                        },
                        "gift_num": {
                            "type": "integer",
                            "description": "抽数（可选，用于筛选特定抽数的奖池）"
                        }
                    },
                    "required": ["pool_id", "gift_id"]
                }
            },
            {
                "name": "query_appearance_config",
                "description": "查询外观资源配置（是否已配置及最大有效期）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "appearance_id": {
                            "type": "integer",
                            "description": "外观ID"
                        }
                    },
                    "required": ["appearance_id"]
                }
            },
            {
                "name": "query_reward_config",
                "description": "查询奖励配置（有效期和最大有效期）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "reward_id": {
                            "type": "integer",
                            "description": "奖励ID（与element_id、event_id三选一）"
                        },
                        "element_id": {
                            "type": "integer",
                            "description": "礼物/外观ID（与reward_id、event_id三选一）"
                        },
                        "event_id": {
                            "type": "integer",
                            "description": "活动ID（与reward_id、element_id三选一）"
                        }
                    }
                }
            }
        ]
    }


@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """调用工具"""
    try:
        if (request.env or "uat") != "uat":
            raise HTTPException(
                status_code=403,
                detail=f"系统仅支持 UAT 环境，当前环境: {request.env}"
            )

        logger.info(f"调用工具: {request.name}, 参数: {request.arguments}")
        
        if request.name == "query_user_info":
            result = query_user_info(**request.arguments)
        elif request.name == "get_verify_code":
            result = query_verify_code(**request.arguments)
        elif request.name == "add_gift_to_exclusive_tab":
            from business_logic.gift import add_to_exclusive_tab
            result = add_to_exclusive_tab(**request.arguments)
        elif request.name == "add_gift_to_backpack":
            from business_logic.gift import add_to_backpack
            result = add_to_backpack(**request.arguments)
        elif request.name == "query_gift_records":
            from business_logic.gift import query_gift_records
            records = query_gift_records(**request.arguments)
            result = {
                "success": True,
                "message": f"找到 {len(records)} 条记录" if records else "未找到相关记录",
                "data": records
            }
        elif request.name == "check_gift_type":
            from business_logic.gift import get_gift_type, get_gift_type_name, can_add_to_backpack, can_add_to_exclusive_tab
            gift_id = request.arguments.get("gift_id")
            gift_type = get_gift_type(gift_id)
            if gift_type is None:
                result = {
                    "success": False,
                    "message": f"无效的礼物ID: {gift_id}"
                }
            else:
                can_backpack, _ = can_add_to_backpack(gift_id)
                can_exclusive, _ = can_add_to_exclusive_tab(gift_id, None, None)
                result = {
                    "success": True,
                    "gift_id": gift_id,
                    "gift_type": gift_type.value,
                    "gift_type_name": get_gift_type_name(gift_type),
                    "can_add_to_backpack": can_backpack,
                    "can_add_to_exclusive_tab": can_exclusive
                }
        elif request.name == "query_pool_config":
            from business_logic.pool import query_pool_config
            result = query_pool_config(**request.arguments)
        elif request.name == "query_gifts_by_name":
            from business_logic.pool import query_gifts_by_name
            result = query_gifts_by_name(**request.arguments)
        elif request.name == "query_gift_info":
            from business_logic.common import query_gift_info
            result = query_gift_info(**request.arguments)
        elif request.name == "list_gift_types":
            from business_logic.gift import list_gift_types
            result = list_gift_types()
        elif request.name == "update_pool_gift_weight_to_max":
            from business_logic.pool import update_pool_gift_weight_to_max
            result = update_pool_gift_weight_to_max(**request.arguments)
        elif request.name == "query_appearance_config":
            from business_logic.config_check import query_appearance_config
            result = query_appearance_config(**request.arguments)
        elif request.name == "query_reward_config":
            from business_logic.config_check import query_reward_config
            result = query_reward_config(**request.arguments)
        else:
            raise HTTPException(status_code=404, detail=f"未知的工具: {request.name}")
        
        logger.info(f"工具调用结果: {result.get('success', False)}")
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": str(result)
                }
            ]
        }
    except Exception as e:
        logger.error(f"工具调用失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """健康检查"""
    from business_logic.common import test_connection
    db_ok = test_connection()
    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database": "connected" if db_ok else "disconnected"
    }


if __name__ == "__main__":
    import os
    
    # 从环境变量读取端口，默认 8003
    port = int(os.getenv("MCP_SERVER_PORT", "8003"))
    
    logger.info("启动本地 MCP 服务器...")
    logger.info(f"地址: http://localhost:{port}")
    logger.info(f"工具列表: http://localhost:{port}/tools/list")
    uvicorn.run(app, host="0.0.0.0", port=port)
