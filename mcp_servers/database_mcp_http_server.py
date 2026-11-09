#!/usr/bin/env python3
"""
数据库查询 MCP HTTP 服务器
提供标准的 MCP HTTP 接口
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import uvicorn
from database_query_server import handle_tool_call, TOOLS

app = FastAPI(title="Database Query MCP Server", version="1.0.0")


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
        "name": "database-query-server",
        "version": "1.0.0",
        "description": "数据库查询 MCP 服务器 - 直接查询 MySQL 数据库"
    }


@app.get("/tools/list")
async def list_tools():
    """列出所有可用工具"""
    return {"tools": TOOLS}


@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """调用工具"""
    try:
        if (request.env or "uat") != "uat":
            raise HTTPException(
                status_code=403,
                detail=f"系统仅支持 UAT 环境，当前环境: {request.env}"
            )

        result = handle_tool_call(request.name, request.arguments)
        return {
            "content": [
                {
                    "type": "text",
                    "text": str(result)
                }
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print("启动数据库查询 MCP 服务器...")
    print("地址: http://localhost:8004")
    print("工具列表: http://localhost:8004/tools/list")
    uvicorn.run(app, host="0.0.0.0", port=8004)
