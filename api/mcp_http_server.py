"""
HTTP入口层 - 适配测试助手

接收工作流平台透传的请求，调用 Skill Agent 执行，返回企微格式化结果。

执行链路：
企微 Bot → 工作流平台 → 公网代理 → 内网UAT → 本服务
"""
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import time
import logging
import uuid
import re
from collections import deque
import os
import requests

# 内存缓存：存储已处理的消息ID（防止重复处理）
_processed_messages: Dict[str, float] = {}  # {msg_id: timestamp}
_CACHE_EXPIRE_SECONDS = 300  # 5分钟过期

from agent_core import SkillCore, SkillAgent
from agent_core.async_skill_agent import AsyncSkillAgent
from agent_core.protocol import SkillInput
from main_business import main as init_business
from utils.result_formatter import format_wechat_card, format_wechat_table
from utils.logging_config import setup_logging, get_logger
from utils.message_formatter import MessageFormatter
from utils.metrics import (
    get_metrics_collector, 
    increment_counter, 
    timer, 
    record_error,
    get_metrics
)
from utils.monitoring import (
    trace_span,
    get_trace_summary,
    clear_trace_context,
    record_http_request,
    get_current_trace_context
)
from utils.idempotent import (
    check_idempotent,
    save_idempotent_result
)
from utils.exceptions import (
    BusinessError,
    ErrorCode,
    EnvNotAllowedError,
    SkillNotFoundError
)
from utils.audit_logger import audit_skill_execution
from utils.config_watcher import start_config_watching, stop_config_watching
from utils.cache_manager import get_cache_manager
from utils.async_executor import get_async_task_queue
from utils.config_loader import ConfigLoader
from utils.wecom_crypto import WeComCrypto, WeComCryptoError, parse_xml_text

# 配置日志
setup_logging(
    log_level="INFO",
    log_dir="logs",
    log_file="mcp_server.log",
    enable_console=True,
    enable_file=True,
    enable_structured=False
)
logger = get_logger(__name__)

app = FastAPI(
    title="AI测试助手HTTP网关",
    description="适配企微→工作流→公网代理→内网UAT的HTTP入口",
    version="1.2.0"
)

# 全局实例
skill_core: Optional[SkillCore] = None
skill_agents: Dict[str, SkillAgent] = {}
async_skill_agents: Dict[str, AsyncSkillAgent] = {}
cache_manager = None
task_queue = None

# 轻量会话记忆（进程内）
SESSION_TTL_SECONDS = 600
SESSION_MAX_TURNS = 5
session_memory_store: Dict[str, Dict[str, Any]] = {}
EXECUTE_CONFIRM_WORDS = {"确认", "确认执行", "执行", "继续执行"}
EXECUTE_CANCEL_WORDS = {"取消", "取消执行", "放弃"}

# 企微配置（优先环境变量）
WECOM_TOKEN = os.getenv("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")
WECOM_SECRET = os.getenv("WECOM_SECRET", "")
WECOM_DEFAULT_BIZ = os.getenv("WECOM_DEFAULT_BIZ", "testops")
WECOM_BOT_NAME = os.getenv("WECOM_BOT_NAME", "Ear")
_wecom_access_token_cache: Dict[str, Any] = {"token": None, "expire_at": 0}


def _get_default_business_code() -> Optional[str]:
    """仅当且仅当已注册一个业务时返回默认业务代码"""
    business_codes = list(async_skill_agents.keys())
    if len(business_codes) == 1:
        return business_codes[0]
    return None


# ========== 全局异常处理器 ==========

@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    """
    业务异常处理器
    
    捕获所有 BusinessError 异常，返回统一格式的错误响应。
    """
    # 获取 trace_id
    ctx = get_current_trace_context()
    trace_id = exc.trace_id or (ctx.trace_id if ctx else None) or getattr(request.state, "trace_id", None)
    
    # 记录错误日志
    logger.warning(
        f"业务异常: [{exc.code}] {exc.message} "
        f"(trace_id: {trace_id})"
    )
    
    # 记录错误指标
    increment_counter(
        "business_errors_total",
        labels={"error_code": exc.code}
    )
    
    # 构造响应
    sanitized_message = MessageFormatter.sanitize_error_message(exc.message)
    response_data = {
        "code": exc.code,
        "msg": sanitized_message,
        "data": exc.data,
        "success": False
    }
    
    if trace_id:
        response_data["trace_id"] = trace_id
    
    # 清空追踪上下文
    clear_trace_context()
    
    return JSONResponse(
        status_code=200,  # 业务异常返回 200，通过 code 区分
        content=response_data
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    HTTP 异常处理器
    
    捕获 FastAPI 的 HTTPException，转换为统一格式。
    """
    # 获取 trace_id
    ctx = get_current_trace_context()
    trace_id = (ctx.trace_id if ctx else None) or getattr(request.state, "trace_id", None)
    
    # 记录错误日志
    logger.warning(
        f"HTTP 异常: [{exc.status_code}] {exc.detail} "
        f"(trace_id: {trace_id})"
    )
    
    # 记录错误指标
    increment_counter(
        "http_errors_total",
        labels={"status_code": str(exc.status_code)}
    )
    
    # 映射 HTTP 状态码到错误码
    error_code_map = {
        400: ErrorCode.INVALID_PARAM,
        404: ErrorCode.SKILL_NOT_FOUND,
        403: ErrorCode.PERMISSION_DENIED,
        500: ErrorCode.SYSTEM_ERROR,
    }
    error_code = error_code_map.get(exc.status_code, ErrorCode.SYSTEM_ERROR)
    
    # 构造响应
    sanitized_detail = MessageFormatter.sanitize_error_message(str(exc.detail))
    response_data = {
        "code": error_code,
        "msg": sanitized_detail,
        "data": {},
        "success": False
    }
    
    if trace_id:
        response_data["trace_id"] = trace_id
    
    # 清空追踪上下文
    clear_trace_context()
    
    return JSONResponse(
        status_code=200,  # 统一返回 200
        content=response_data
    )


@app.exception_handler(Exception)
async def system_error_handler(request: Request, exc: Exception):
    """
    系统异常处理器
    
    捕获所有未处理的异常，返回统一格式的错误响应。
    """
    # 获取 trace_id
    ctx = get_current_trace_context()
    trace_id = (ctx.trace_id if ctx else None) or getattr(request.state, "trace_id", None)
    
    # 记录错误日志（包含堆栈信息）
    logger.error(
        f"系统异常: {type(exc).__name__}: {str(exc)} "
        f"(trace_id: {trace_id})",
        exc_info=True
    )
    
    # 记录错误指标
    increment_counter(
        "system_errors_total",
        labels={"exception_type": type(exc).__name__}
    )
    
    # 构造响应
    sanitized_message = MessageFormatter.sanitize_error_message(f"系统错误: {str(exc)}")
    response_data = {
        "code": ErrorCode.SYSTEM_ERROR,
        "msg": sanitized_message,
        "data": {
            "exception_type": type(exc).__name__
        },
        "success": False
    }
    
    if trace_id:
        response_data["trace_id"] = trace_id
    
    # 清空追踪上下文
    clear_trace_context()
    
    return JSONResponse(
        status_code=200,  # 统一返回 200
        content=response_data
    )


@app.on_event("startup")
async def startup_event():
    """启动时初始化业务"""
    global skill_core, skill_agents, async_skill_agents, cache_manager, task_queue
    logger.info("=" * 60)
    logger.info("启动 AI测试助手HTTP网关")
    logger.info("=" * 60)
    
    # 初始化业务
    skill_core = init_business()

    # 按配置初始化各业务 Agent
    businesses = ConfigLoader.load_enabled_businesses()

    for business_code in businesses:
        skill_agents[business_code] = SkillAgent(business_code, skill_core)
        async_skill_agents[business_code] = AsyncSkillAgent(business_code, skill_core)
    logger.info(f"✓ 异步 SkillAgent 已初始化，业务数量: {len(businesses)}")
    
    # 初始化缓存管理器
    try:
        cache_manager = get_cache_manager()
        logger.info("✓ 缓存管理器已初始化")
    except Exception as e:
        logger.warning(f"缓存管理器初始化失败: {e}")
    
    # 初始化异步任务队列
    try:
        task_queue = get_async_task_queue()
        logger.info("✓ 异步任务队列已初始化")
    except Exception as e:
        logger.warning(f"异步任务队列初始化失败: {e}")
    
    # 启动配置监听
    def on_config_change(file_path: str):
        """配置变更回调 - 重新加载对应的配置"""
        logger.info(f"配置文件已更新: {file_path}")
        
        try:
            # 根据文件路径判断需要重新加载哪个配置
            if "skills_registry.json" in file_path:
                logger.info("重新加载 Skills 注册表...")
                # 注意：缓存不会自动清除，需要重启服务生效
                    
            elif "intent_rules.json" in file_path:
                logger.info("重新加载意图匹配规则...")
                # 注意：缓存不会自动清除，需要重启服务生效
                    
            elif "param_completion_rules.json" in file_path:
                logger.info("重新加载参数补全规则...")
                # 参数补全规则会在下次使用时自动重新加载
                
            elif "llm_prompts.json" in file_path:
                logger.info("重新加载 LLM Prompt 配置...")
                # LLM Prompt 会在下次使用时自动重新加载
                
            else:
                logger.info(f"配置文件更新: {file_path}，将在下次使用时自动重新加载")
                
        except Exception as e:
            logger.error(f"配置重新加载失败: {e}", exc_info=True)
    
    try:
        start_config_watching(
            paths=["config/framework", "config/business"],
            callback=on_config_change
        )
        logger.info("✓ 配置监听已启动")
    except Exception as e:
        logger.warning(f"配置监听启动失败: {e}")
    
    logger.info("✓ HTTP服务启动完成")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时清理资源"""
    logger.info("正在关闭服务...")
    
    # 停止配置监听
    try:
        stop_config_watching()
        logger.info("✓ 配置监听已停止")
    except Exception as e:
        logger.warning(f"配置监听停止失败: {e}")
    
    logger.info("✓ 服务已关闭")


class TestOpsRequest(BaseModel):
    """测试助手请求（适配工作流平台）"""
    user_input: str = Field(..., description="用户指令")
    session_id: Optional[str] = Field(default=None, description="会话ID")
    request_id: Optional[str] = Field(default=None, description="请求ID（用于幂等性）")
    operator: Optional[str] = Field(default="test01", description="操作人账号")
    source: Optional[str] = Field(default=None, description="请求来源：wecom/workflow/local")
    env: Optional[str] = Field(default="uat", description="执行环境：uat/prod")
    business_code: Optional[str] = Field(default=None, description="业务代码（可选；仅注册一个业务时可省略）")


class TestOpsResponse(BaseModel):
    """测试助手响应"""
    code: int = Field(description="状态码：0=成功，非0=失败")
    msg: str = Field(description="提示信息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="业务数据")
    success: bool = Field(description="是否成功")
    risk_tips: Optional[str] = Field(default=None, description="风险提示信息")
    operation_log_id: Optional[str] = Field(default=None, description="操作日志ID")


@app.post("/api/testops/skill/execute", response_model=TestOpsResponse)  # 兼容旧入口
@app.post("/api/{path_business_code}/skill/execute", response_model=TestOpsResponse)
@trace_span("http_execute_skill")
async def execute_testops_skill(request: TestOpsRequest, path_business_code: Optional[str] = None):
    """
    执行测试助手 Skill（异步版本 + 全链路追踪）
    
    接收工作流平台透传的请求，执行 Skill，返回企微格式化结果。
    
    ⚠️ 环境限制：仅支持 UAT 环境，生产环境操作已被禁止
    
    执行流程：
    1. 环境检查（强制 UAT）
    2. 提取核心参数
    3. 异步 LLM 解析意图和参数
    4. 调度 Skill 执行
    5. 格式化结果
    6. 返回结果
    
    性能优化：
    - 异步 LLM 调用
    - 意图缓存（10-150x 加速）
    - 配置缓存（260x 加速）
    
    可观测性：
    - 全链路追踪
    - 详细业务指标
    - 性能监控
    """
    start_time = time.time()
    
    request_endpoint = f"/api/{path_business_code}/skill/execute" if path_business_code else "/api/testops/skill/execute"
    increment_counter("http_requests_total", labels={"endpoint": request_endpoint})
    
    try:
        # 1. 环境检查：强制 UAT 环境
        env = request.env or "uat"
        if env != "uat":
            logger.warning(f"拒绝非UAT环境请求: {env}")
            increment_counter("http_requests_rejected", labels={"reason": "invalid_env"})
            
            duration_ms = (time.time() - start_time) * 1000
            record_http_request(
                endpoint=request_endpoint,
                method="POST",
                status_code=403,
                duration_ms=duration_ms
            )
            
            # 抛出统一异常
            raise EnvNotAllowedError(
                message=f"系统仅支持 UAT 环境，当前环境: {env}。生产环境操作已被禁止。",
                data={"env": env, "allowed_env": "uat"}
            )
    
        # 2. 提取核心参数
        user_input = request.user_input
        session_id = request.session_id or f"session_{int(time.time())}"
        request_id = request.request_id  # 幂等性请求ID
        operator = _normalize_operator(request.operator, request.source)
        env = "uat"  # 强制 UAT 环境
        business_code = request.business_code or path_business_code or _get_default_business_code()
        if not business_code:
            raise BusinessError(
                code=ErrorCode.INVALID_PARAM,
                message="缺少 business_code，且当前存在多个已注册业务",
                data={"available_businesses": list(async_skill_agents.keys())}
            )
        
        logger.info(
            f"收到请求 - 用户输入: {user_input}, "
            f"操作人: {operator}, 环境: {env} (强制UAT), "
            f"请求ID: {request_id or '未提供'}"
        )
        
        # 3. 幂等性检查（仅对有 request_id 的请求）
        if request_id:
            cached_result = check_idempotent(
                request_id=request_id,
                business_code=business_code,
                operator=operator
            )
            
            if cached_result:
                logger.info(f"幂等性检查命中，返回缓存结果: request_id={request_id}")
                increment_counter("idempotent_cache_hit", labels={"business_code": business_code})
                
                duration_ms = (time.time() - start_time) * 1000
                record_http_request(
                    endpoint=request_endpoint,
                    method="POST",
                    status_code=200,
                    duration_ms=duration_ms
                )
                
                # 添加幂等性标识
                if isinstance(cached_result.get("data"), dict):
                    cached_result["data"]["idempotent"] = True
                    cached_result["data"]["cached_at"] = cached_result.get("cached_at")
                
                return TestOpsResponse(**cached_result)
        
        # 4. 获取对应业务的 AsyncSkillAgent
        async_agent = async_skill_agents.get(business_code)
        if not async_agent:
            # 抛出统一异常
            raise SkillNotFoundError(
                message=f"业务代码未找到: {business_code}",
                data={"business_code": business_code}
            )
        
        # 4. 异步 LLM 解析意图和参数（传递上下文）
        context = {
            "operator": operator,
            "env": env,
            "session_id": session_id,
            "operator_source": request.source
        }

        _cleanup_expired_session_memory()
        session_key = _get_session_key(
            business_code=business_code,
            session_id=session_id,
            operator=operator,
            source=request.source
        )
        memory = session_memory_store.get(session_key)
        pending_execute = memory.get("pending_execute") if memory else None
        if pending_execute:
            if _is_execute_cancel(user_input):
                memory.pop("pending_execute", None)
                session_memory_store[session_key] = memory
                return TestOpsResponse(
                    code=400,
                    msg="已取消本次待执行操作。",
                    data={"pending_execute": False},
                    success=False
                )
            if _is_execute_confirm(user_input):
                user_input = pending_execute.get("composed_input") or pending_execute.get("base_input")
                context["execute_confirmed"] = True
                memory.pop("pending_execute", None)
                session_memory_store[session_key] = memory
                logger.info(f"收到执行确认，继续执行待处理指令: session_key={session_key}")
            else:
                composed_input = f"{pending_execute.get('base_input', '')}，{user_input}".strip("，")
                pending_execute["composed_input"] = composed_input
                pending_execute["updated_at"] = int(time.time())
                memory["pending_execute"] = pending_execute
                session_memory_store[session_key] = memory
                return TestOpsResponse(
                    code=400,
                    msg="已记录补充参数。请回复“确认执行”继续，或回复“取消”放弃。",
                    data={
                        "pending_execute": True,
                        "skill_name": pending_execute.get("skill_name"),
                        "composed_input": composed_input
                    },
                    success=False
                )

        result = await async_agent.process(user_input, context=context)

        if result.get("status") == "blocked" and (result.get("data") or {}).get("pending_execute"):
            session_memory_store[session_key] = {
                "updated_at": time.time(),
                "turns": [],
                "pending_execute": {
                    "skill_name": result.get("skill_name"),
                    "base_input": user_input,
                    "composed_input": user_input,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time())
                }
            }
        
        # 检查 LLM 解析是否成功
        if not result.get("success"):
            duration_ms = (time.time() - start_time) * 1000
            record_http_request(
                endpoint=request_endpoint,
                method="POST",
                status_code=400,
                duration_ms=duration_ms
            )
            
            return TestOpsResponse(
                code=400,
                msg=MessageFormatter.sanitize_error_message(result.get("message", "意图识别失败")),
                data=result.get("data"),
                success=False
            )
        
        # 5. 如果 async_agent.process 已经执行了 Skill，直接返回结果
        if result.get("data") is not None:
            # async_agent.process 已经执行完成，直接格式化返回
            skill_output_data = result.get("data", {})
            
            # 添加追踪信息
            trace_summary = get_trace_summary()
            if trace_summary:
                skill_output_data["trace"] = trace_summary
            
            # 添加性能信息
            if "performance" in result:
                skill_output_data["performance"] = result["performance"]
            
            # 清空追踪上下文
            clear_trace_context()
            
            # 记录 HTTP 请求指标
            duration_ms = (time.time() - start_time) * 1000
            status_code = 200 if result.get("success") else 500
            record_http_request(
                endpoint=request_endpoint,
                method="POST",
                status_code=status_code,
                duration_ms=duration_ms
            )
            
            # 构造响应
            response_code = 0 if result.get("success") else 400 if result.get("status") == "blocked" else 500
            response_data = {
                "code": response_code,
                "msg": MessageFormatter.sanitize_error_message(result.get("message", "执行成功")),
                "data": skill_output_data,
                "success": result.get("success", False),
                "risk_tips": "✅ UAT环境执行（异步 + 追踪）",
                "operation_log_id": None
            }
            
            # 保存幂等性结果（仅对执行类操作）
            if request_id and result.get("success"):
                skill_name = result.get("skill_name")
                params = result.get("params")
                
                # 添加缓存时间戳
                response_data["cached_at"] = time.time()
                
                save_idempotent_result(
                    result=response_data,
                    request_id=request_id,
                    business_code=business_code,
                    skill_name=skill_name,
                    params=params,
                    operator=operator
                )
                logger.info(f"幂等性结果已保存: request_id={request_id}, skill={skill_name}")
                increment_counter("idempotent_cache_save", labels={"business_code": business_code})
            
            # 构造 SkillOutput 格式的响应
            return TestOpsResponse(**response_data)
        
        # 6. 格式化结果（适配企微渲染）
        skill_output_data = result.get("data", {})
        if skill_output_data:
            if skill_output_data.get("format") == "wechat_card":
                card_data = skill_output_data.get("card_data")
                if card_data:
                    formatted_result = format_wechat_card(card_data)
                    skill_output_data["formatted_result"] = formatted_result
            
            elif skill_output_data.get("format") == "wechat_table":
                table_data = skill_output_data.get("table_data")
                if table_data:
                    formatted_result = format_wechat_table(table_data)
                    skill_output_data["formatted_result"] = formatted_result
        
        # 7. 返回结果
        logger.info(
            f"执行完成 - Skill: {result.get('skill_name')}, "
            f"状态: {result.get('success')}"
        )
        
        # 记录审计日志
        ctx = get_current_trace_context()
        audit_skill_execution(
            operator=operator,
            skill_name=result.get("skill_name", "unknown"),
            params=result.get("params", {}),
            result=skill_output_data,
            success=result.get("success", False),
            error=result.get("error") if not result.get("success") else None,
            trace_id=ctx.trace_id if ctx else None,
            session_id=session_id,
            env=env,
            duration_ms=(time.time() - start_time) * 1000
        )
        
        # 记录 HTTP 请求指标
        duration_ms = (time.time() - start_time) * 1000
        status_code = 200 if result.get("success") else 500
        record_http_request(
            endpoint=request_endpoint,
            method="POST",
            status_code=status_code,
            duration_ms=duration_ms
        )
        
        # 清空追踪上下文
        clear_trace_context()
        
        return TestOpsResponse(
            code=0 if result.get("success") else 500,
            msg=MessageFormatter.sanitize_error_message(result.get("message", "执行完成")),
            data=skill_output_data,
            success=result.get("success", False),
            risk_tips="✅ UAT环境执行（异步 + 追踪）",
            operation_log_id=None
        )
        
        # 全局异常处理器会自动捕获所有异常（不需要 except 块）
    except BusinessError:
        # 业务异常由全局处理器处理
        raise
    except Exception:
        # 系统异常由全局处理器处理
        raise


# 兼容旧接口
class SkillRequest(BaseModel):
    business_code: str
    user_input: str
    context: Optional[Dict[str, Any]] = None


# 工作流平台专用接口（兼容 message 字段）
class WorkflowRequest(BaseModel):
    message: str = Field(..., description="用户消息（工作流平台格式）")
    business_code: Optional[str] = Field(default=None, description="业务代码（可选；仅注册一个业务时可省略）")
    operator: Optional[str] = Field(default="workflow", description="操作人")
    source: Optional[str] = Field(default=None, description="请求来源：wecom/workflow/local")
    env: Optional[str] = Field(default="uat", description="环境")


def _normalize_operator(operator: Optional[str], source: Optional[str]) -> str:
    """操作人归一化：来源优先，operator 其次，最终回填固定默认值。"""
    source_value = (source or "").strip().lower()
    operator_value = (operator or "").strip()
    if source_value:
        return source_value
    if operator_value:
        return operator_value
    return "ear_agent/test_user"


def _get_session_key(
    business_code: Optional[str],
    session_id: Optional[str],
    operator: Optional[str],
    source: Optional[str]
) -> str:
    if session_id:
        return f"{business_code or 'default'}:sid:{session_id}"
    return f"{business_code or 'default'}:op:{operator or 'unknown'}:src:{(source or 'local').lower()}"


def _cleanup_expired_session_memory():
    now = time.time()
    expired_keys = [
        key for key, value in session_memory_store.items()
        if now - value.get("updated_at", now) > SESSION_TTL_SECONDS
    ]
    for key in expired_keys:
        session_memory_store.pop(key, None)


def _is_param_only_followup(user_input: str) -> bool:
    text = (user_input or "").strip()
    if not text or len(text) > 40:
        return False
    return bool(re.search(r"(id|活动|用户|直播间|礼物|奖池|pool|gift|user|room)\s*[:：= ]\s*\d+", text, re.IGNORECASE))


def _is_execute_confirm(user_input: str) -> bool:
    return (user_input or "").strip().lower() in {w.lower() for w in EXECUTE_CONFIRM_WORDS}


def _is_execute_cancel(user_input: str) -> bool:
    return (user_input or "").strip().lower() in {w.lower() for w in EXECUTE_CANCEL_WORDS}


def _mask_secret(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}***{value[-keep:]}"


def _load_reply_hints(business_code: str) -> Dict[str, Any]:
    try:
        cfg = ConfigLoader.load_business_config(business_code, "reply_hints.json")
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _detect_status_icon(result: Dict[str, Any]) -> str:
    message = (result.get("message") or "").lower()
    if result.get("success"):
        return "✅"
    if result.get("degraded") or "缺少" in message or "补充" in message:
        return "‼️"
    if "确认执行" in message or "拦截" in message:
        return "⚠️"
    return "❌"


def _append_business_hints(result: Dict[str, Any], user_input: str, business_code: str) -> Dict[str, Any]:
    # 如果result不是字典，直接返回包装后的错误
    if not isinstance(result, dict):
        logger.warning(f"_append_business_hints received non-dict result: {type(result)}")
        return {"success": False, "message": "系统返回了意外的数据格式", "data": result}
    
    message = (result.get("message") or "").strip()
    if not message:
        return result

    icon = _detect_status_icon(result)
    if not message.startswith(("✅", "❌", "‼️", "⚠️")):
        message = f"{icon} {message}"

    cfg = _load_reply_hints(business_code)
    skill_hints = cfg.get("skill_hints", {})
    default_hints = cfg.get("default_hints", [])
    skill_name = result.get("skill_name") or (result.get("intent") or {}).get("skill_name")
    hints = skill_hints.get(skill_name, [])
    if not hints and "钻石" in (user_input or ""):
        hints = skill_hints.get("top_up_diamond", [])
    if not hints:
        hints = default_hints

    should_append_hints = (
        not result.get("success")
        or bool(result.get("degraded"))
        or bool((result.get("data") or {}).get("need_refine") if isinstance(result.get("data"), dict) else False)
    )

    if hints and should_append_hints:
        # 检查消息中是否已经包含参考指令，避免重复添加
        if "💡 参考指令：" not in message and "可参考以下指令模板" not in message:
            hint_lines = "\n".join([f"• {h}" for h in hints[:2]])
            message = f"{message}\n\n💡 参考指令：\n{hint_lines}"

    result["message"] = message
    return result


def _build_wecom_crypto() -> WeComCrypto:
    return WeComCrypto(WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID)


def _clean_expired_messages():
    """清理过期的消息缓存"""
    now = time.time()
    expired_keys = [
        msg_id for msg_id, timestamp in _processed_messages.items()
        if now - timestamp > _CACHE_EXPIRE_SECONDS
    ]
    for key in expired_keys:
        _processed_messages.pop(key, None)
    if expired_keys:
        logger.debug(f"清理过期消息缓存: {len(expired_keys)} 条")


def _is_msg_processed(msg_id: str) -> bool:
    """检查消息是否已处理"""
    _clean_expired_messages()  # 顺便清理过期数据
    return msg_id in _processed_messages


def _mark_msg_processing(msg_id: str):
    """标记消息为处理中"""
    _processed_messages[msg_id] = time.time()


async def _process_wecom_message_async(
    agent,
    user_input: str,
    context: dict,
    from_user: str,
    chat_id: str,
    is_group_chat: bool,
    msg_id: str,
    business_code: str
):
    """异步处理企微消息（后台任务）"""
    try:
        result = await agent.process(user_input, context=context)
        result = _append_business_hints(result, user_input=user_input, business_code=business_code)
        
        # 构建回复消息
        message = result.get("message") or ("执行成功" if result.get("success") else "执行失败")
        # 过滤敏感信息
        message = MessageFormatter.sanitize_error_message(message)
        skill_name = result.get("skill_name")
        
        # 对于批量操作，只显示汇总信息，不显示详细数据
        if skill_name == "multi_operations":
            reply = message  # 已经包含了汇总和简要结果
        else:
            # 如果有数据，格式化并添加到消息中
            data = result.get("data")
            if data and result.get("success"):
                formatted_data = _format_result_data(data, skill_name)
                if formatted_data:
                    reply = f"{message}\n\n{formatted_data}"
                else:
                    reply = message
            else:
                reply = message

        # 主动回复用户
        try:
            if is_group_chat:
                _send_wecom_group_text(chat_id, reply)
            else:
                _send_wecom_text(from_user, reply)
        except Exception as send_err:
            logger.error(f"企微主动回消息失败: {send_err}")
    except Exception as e:
        logger.error(f"异步处理企微消息失败: {e}", exc_info=True)
    finally:
        # 处理完成后，保持消息ID在缓存中（防止重复），会在过期后自动清理
        pass


def _format_result_data(data: Any, skill_name: str = None) -> str:
    """
    格式化结果数据为可读文本
    
    Args:
        data: 结果数据
        skill_name: 技能名称
        
    Returns:
        格式化后的文本
    """
    if not data:
        return ""
    
    try:
        # 查询礼物信息
        if skill_name == "query_gift_info":
            if isinstance(data, dict):
                # 单个礼物
                gift_id = data.get('gift_id')
                price = data.get('price')
                # 转换为整数（如果是整数值）
                if isinstance(gift_id, float) and gift_id.is_integer():
                    gift_id = int(gift_id)
                if isinstance(price, float) and price.is_integer():
                    price = int(price)
                
                lines = [
                    f"📦 礼物ID: {gift_id}",
                    f"🎁 名称: {data.get('name')}",
                    f"🏷️ 类型: {data.get('type_name', data.get('type'))}",
                    f"💰 价格: {price} 钻石",
                ]
                if data.get('intro'):
                    lines.append(f"📝 简介: {data.get('intro')}")
                return "\n".join(lines)
            elif isinstance(data, list) and len(data) > 0:
                # 多个礼物
                # 如果礼物数量较少（<=3个），显示详细格式
                if len(data) <= 3:
                    result_lines = []
                    for item in data:
                        gift_id = item.get('gift_id')
                        price = item.get('price')
                        # 转换为整数（如果是整数值）
                        if isinstance(gift_id, float) and gift_id.is_integer():
                            gift_id = int(gift_id)
                        if isinstance(price, float) and price.is_integer():
                            price = int(price)
                        
                        lines = [
                            f"📦 礼物ID: {gift_id}",
                            f"🎁 名称: {item.get('name')}",
                            f"🏷️ 类型: {item.get('type_name', item.get('type'))}",
                            f"💰 价格: {price} 钻石",
                        ]
                        if item.get('intro'):
                            lines.append(f"📝 简介: {item.get('intro')}")
                        result_lines.append("\n".join(lines))
                    
                    return "\n\n".join(result_lines)
                else:
                    # 礼物数量较多，使用简略格式
                    lines = []
                    for item in data[:10]:  # 最多显示10个
                        gift_id = item.get('gift_id')
                        price = item.get('price')
                        # 转换为整数（如果是整数值）
                        if isinstance(gift_id, float) and gift_id.is_integer():
                            gift_id = int(gift_id)
                        if isinstance(price, float) and price.is_integer():
                            price = int(price)
                        
                        lines.append(
                            f"• {gift_id} - {item.get('name')} "
                            f"({item.get('type_name', item.get('type'))}, {price}钻)"
                        )
                    if len(data) > 10:
                        lines.append(f"... 还有 {len(data) - 10} 个结果")
                    return "\n".join(lines)
        
        # 查询用户信息
        elif skill_name == "query_user_info":
            if isinstance(data, dict):
                lines = [
                    f"👤 用户ID: {data.get('user_id')}",
                    f"✨ 昵称: {data.get('username') or '未设置'}",
                    f"📱 手机号: {data.get('phone', '未绑定')}",
                    f"📧 邮箱: {data.get('email') or '未绑定'}",
                ]
                if data.get('room_id'):
                    lines.append(f"🏠 直播间ID: {data.get('room_id')}")
                    if data.get('room_name'):
                        lines.append(f"🎙️ 直播间名称: {data.get('room_name')}")
                return "\n".join(lines)
        
        # 查询奖池配置
        elif skill_name == "query_pool_config":
            # 处理单个奖池（字典）
            if isinstance(data, dict) and 'pool_id' in data:
                pool_id = data.get('pool_id')
                gift_num = data.get('gift_num', 0)
                has_guarantee = data.get('has_guarantee', False)
                miss_limit = data.get('miss_limit')
                ssr_id = data.get('ssr_id')
                
                lines = [
                    f"🎰 奖池ID: {pool_id}",
                    f"📦 礼物数量: {gift_num}",
                ]
                
                if has_guarantee:
                    lines.append(f"🎯 保底机制: 是（{miss_limit}次未中后必得SSR {ssr_id}）")
                else:
                    lines.append(f"🎯 保底机制: 否")
                
                # 显示概率分布
                probabilities = data.get('probabilities', {})
                if probabilities:
                    lines.append(f"\n📊 礼物概率分布:")
                    for gift_id, prob_info in probabilities.items():
                        name = prob_info.get('name', '未知')
                        probability = prob_info.get('probability', 0)
                        weight = prob_info.get('weight', 0)
                        diamond = prob_info.get('diamond', 0)
                        lines.append(f"  • {gift_id} - {name} ({diamond}钻)")
                        lines.append(f"    权重: {weight}, 概率: {probability}%")
                
                return "\n".join(lines)
            
            # 处理多个奖池（列表）
            elif isinstance(data, list) and len(data) > 0:
                lines = []
                for pool in data:
                    pool_id = pool.get('pool_id')
                    gift_num = pool.get('gift_num', 0)
                    has_guarantee = pool.get('has_guarantee', False)
                    miss_limit = pool.get('miss_limit')
                    ssr_id = pool.get('ssr_id')
                    
                    lines.append(f"🎰 奖池ID: {pool_id}")
                    lines.append(f"📦 礼物数量: {gift_num}")
                    if has_guarantee:
                        lines.append(f"🎯 保底机制: 是（{miss_limit}次未中后必得SSR {ssr_id}）")
                    else:
                        lines.append(f"🎯 保底机制: 否")
                    
                    # 显示概率分布
                    rates = pool.get('rates', {})
                    if rates:
                        lines.append(f"📊 概率分布:")
                        for rate_type, rate_value in rates.items():
                            lines.append(f"  • {rate_type}: {rate_value}%")
                    
                    lines.append("")  # 空行分隔
                
                return "\n".join(lines)
        
        # 查询后台功能URL
        elif skill_name in ["query_feature_url", "list_features"]:
            if isinstance(data, dict) and 'features' in data:
                features = data.get('features', [])
                if not features:
                    return "未找到相关功能"
                
                lines = []
                for idx, feature in enumerate(features[:10], 1):  # 最多显示10个
                    title = feature.get('title', '未知')
                    url = feature.get('url', '')
                    category = feature.get('category', '')
                    description = feature.get('description', '')
                    
                    lines.append(f"{idx}. {title}")
                    if category:
                        lines.append(f"   分类: {category}")
                    if description and len(description) < 100:
                        lines.append(f"   说明: {description}")
                    lines.append(f"   🔗 {url}")
                    lines.append("")  # 空行分隔
                
                if len(features) > 10:
                    lines.append(f"... 还有 {len(features) - 10} 个结果")
                
                return "\n".join(lines)
        
        # 其他情况，尝试简单格式化
        if isinstance(data, dict):
            # 如果数据较少，直接显示
            if len(data) <= 5:
                lines = [f"{k}: {v}" for k, v in data.items() if v is not None]
                return "\n".join(lines)
        
        return ""
    except Exception as e:
        logger.error(f"格式化数据失败: {e}")
        return ""


def _get_wecom_access_token() -> str:
    now = int(time.time())
    if _wecom_access_token_cache.get("token") and now < _wecom_access_token_cache.get("expire_at", 0):
        return _wecom_access_token_cache["token"]

    if not WECOM_CORP_ID or not WECOM_SECRET:
        raise WeComCryptoError("missing WECOM_CORP_ID or WECOM_SECRET")

    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    resp = requests.get(url, params={"corpid": WECOM_CORP_ID, "corpsecret": WECOM_SECRET}, timeout=8)
    data = resp.json()
    if data.get("errcode") != 0:
        raise WeComCryptoError(f"get access_token failed: {data}")
    token = data.get("access_token")
    expires_in = int(data.get("expires_in", 7200))
    _wecom_access_token_cache["token"] = token
    _wecom_access_token_cache["expire_at"] = now + max(expires_in - 120, 60)
    return token


def _send_wecom_text(touser: str, content: str):
    if not WECOM_AGENT_ID:
        raise WeComCryptoError("missing WECOM_AGENT_ID")
    access_token = _get_wecom_access_token()
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
    payload = {
        "touser": touser,
        "msgtype": "text",
        "agentid": int(WECOM_AGENT_ID),
        "text": {"content": content[:1800]},
        "safe": 0
    }
    resp = requests.post(url, json=payload, timeout=8)
    data = resp.json()
    if data.get("errcode") != 0:
        logger.error(f"企微回消息失败: {data}")


def _send_wecom_group_text(chat_id: str, content: str):
    access_token = _get_wecom_access_token()
    url = f"https://qyapi.weixin.qq.com/cgi-bin/appchat/send?access_token={access_token}"
    payload = {
        "chatid": chat_id,
        "msgtype": "text",
        "text": {"content": content[:1800]},
        "safe": 0
    }
    resp = requests.post(url, json=payload, timeout=8)
    data = resp.json()
    if data.get("errcode") != 0:
        logger.error(f"企微群回消息失败: {data}")


def _normalize_group_user_input(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    bot_tokens = [f"@{WECOM_BOT_NAME}", WECOM_BOT_NAME]
    mentioned = any(token in text for token in bot_tokens) or ("@" in text and " " in text)
    if not mentioned:
        return ""
    for token in bot_tokens:
        text = text.replace(token, "")
    return text.strip()


class SkillResponse(BaseModel):
    success: bool
    code: Optional[str] = None
    data: Optional[Any] = None  # 改为 Any 类型，支持 dict/list/str 等
    message: Optional[str] = None
    error: Optional[str] = None
    intent: Optional[Dict[str, Any]] = None
    params: Optional[Dict[str, Any]] = None
    skill_name: Optional[str] = None
    request_id: Optional[str] = None


class LangGraphAgentRequest(BaseModel):
    user_input: str = Field(..., description="用户输入指令")
    context: Optional[Dict[str, Any]] = Field(default=None, description="执行上下文")


@app.get("/wecom/callback")
@app.get("/agent/execute/wecom/callback")
async def wecom_callback_verify(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    echostr: str
):
    """企微回调URL验证（安全模式）。"""
    try:
        crypto = _build_wecom_crypto()
        if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
            return PlainTextResponse("invalid signature", status_code=403)
        plain = crypto.decrypt(echostr)
        return PlainTextResponse(plain)
    except Exception as e:
        logger.error(f"企微URL验证失败: {e}")
        return PlainTextResponse("verify failed", status_code=500)


@app.get("/wecom/debug/config")
@app.get("/agent/execute/wecom/debug/config")
async def wecom_debug_config():
    """排障：查看当前进程加载到的企微配置（脱敏）。"""
    return {
        "token_loaded": bool(WECOM_TOKEN),
        "token_masked": _mask_secret(WECOM_TOKEN),
        "aes_key_loaded": bool(WECOM_ENCODING_AES_KEY),
        "aes_key_len": len(WECOM_ENCODING_AES_KEY or ""),
        "aes_key_masked": _mask_secret(WECOM_ENCODING_AES_KEY, keep=6),
        "corp_id_loaded": bool(WECOM_CORP_ID),
        "corp_id": WECOM_CORP_ID,
        "agent_id_loaded": bool(WECOM_AGENT_ID),
        "agent_id": WECOM_AGENT_ID,
        "default_biz": WECOM_DEFAULT_BIZ
    }


@app.post("/wecom/callback")
@app.post("/agent/execute/wecom/callback")
async def wecom_callback(
    request: Request,
    msg_signature: str,
    timestamp: str,
    nonce: str
):
    """企微消息回调：解密 -> 透传Agent -> 回发消息（异步处理，立即返回）。"""
    try:
        raw_xml = (await request.body()).decode("utf-8")
        encrypted_obj = parse_xml_text(raw_xml)
        encrypted = encrypted_obj.get("Encrypt", "")
        crypto = _build_wecom_crypto()
        if not crypto.verify_signature(msg_signature, timestamp, nonce, encrypted):
            return PlainTextResponse("invalid signature", status_code=403)

        plain_xml = crypto.decrypt(encrypted)
        msg = parse_xml_text(plain_xml)
        msg_type = (msg.get("MsgType") or "").lower()
        if msg_type != "text":
            return PlainTextResponse("success")

        user_input = (msg.get("Content") or "").strip()
        if not user_input:
            return PlainTextResponse("success")

        # 幂等性检查：使用内存缓存防止重复处理
        msg_id = msg.get("MsgId", "")
        if msg_id and _is_msg_processed(msg_id):
            logger.info(f"消息已处理，跳过: MsgId={msg_id}")
            return PlainTextResponse("success")

        # 标记消息为处理中（防止并发重复）
        if msg_id:
            _mark_msg_processing(msg_id)

        business_code = WECOM_DEFAULT_BIZ or _get_default_business_code()
        agent = async_skill_agents.get(business_code)
        if not agent:
            logger.error(f"企微回调业务未找到: {business_code}")
            return PlainTextResponse("success")

        from_user = msg.get("FromUserName", "")
        to_user = msg.get("ToUserName", "")
        chat_id = msg.get("ChatId") or msg.get("ExternalUserID") or from_user
        is_group_chat = bool(msg.get("ChatId"))
        if is_group_chat:
            # 群聊仅在@机器人或提及机器人名时触发
            normalized = _normalize_group_user_input(user_input)
            if not normalized:
                return PlainTextResponse("success")
            user_input = normalized
        context = {
            "operator": from_user or "wecom_user",
            "operator_source": "wecom",
            "env": "uat",
            "session_id": f"wecom:{chat_id}"
        }

        # 异步处理业务逻辑，立即返回响应（避免超时重试）
        import asyncio
        asyncio.create_task(_process_wecom_message_async(
            agent, user_input, context, from_user, chat_id, is_group_chat, msg_id, business_code
        ))

        # 立即返回成功，避免企微超时重试
        return PlainTextResponse("success")
    except Exception as e:
        logger.error(f"企微回调处理失败: {e}", exc_info=True)
        return PlainTextResponse("success")


@app.get("/agent/execute", response_model=SkillResponse)
async def execute_agent_get(
    message: Optional[str] = Query(default=None, description="用户输入指令"),
    echostr: Optional[str] = Query(default=None, description="企微URL验证回显"),
    msg_signature: Optional[str] = Query(default=None, description="企微签名"),
    timestamp: Optional[str] = Query(default=None, description="企微时间戳"),
    nonce: Optional[str] = Query(default=None, description="企微随机串"),
    business_code: Optional[str] = Query(default=None, description="业务代码"),
    operator: Optional[str] = Query(default="web_get", description="操作人"),
    source: Optional[str] = Query(default="web_get", description="请求来源"),
    session_id: Optional[str] = Query(default=None, description="会话ID"),
    env: Optional[str] = Query(default="uat", description="执行环境")
):
    """
    轻量 GET 入口：
    - 带 echostr：原样纯文本回显（兼容企微验证）
    - 不带 message：用于连通性探测
    - 带 message：透传到 Agent 执行
    """
    if echostr is not None:
        # 兼容企微回调验证：带签名参数时，验签并解密后返回明文
        if msg_signature and timestamp and nonce:
            try:
                crypto = _build_wecom_crypto()
                if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
                    return PlainTextResponse("invalid signature", status_code=403)
                plain = crypto.decrypt(echostr)
                return PlainTextResponse(plain)
            except Exception as e:
                logger.error(f"GET /agent/execute 企微验证失败: {e}")
                return PlainTextResponse("verify failed", status_code=500)
        # 非企微验证场景，保持原样回显
        return PlainTextResponse(echostr)

    if not message:
        return SkillResponse(
            success=True,
            message="agent execute get is reachable",
            data={
                "usage": "GET /agent/execute?message=查询礼物80103&business_code=testops",
                "default_business_code": _get_default_business_code(),
                "supported_env": ["uat"]
            },
            error=None,
            intent=None,
            params=None,
            skill_name=None
        )

    if env != "uat":
        raise EnvNotAllowedError(
            message=f"系统仅支持 UAT 环境，当前环境: {env}。生产环境操作已被禁止。",
            data={"env": env, "allowed_env": "uat"}
        )

    resolved_business_code = business_code or _get_default_business_code()
    if not resolved_business_code:
        raise BusinessError(
            code=ErrorCode.INVALID_PARAM,
            message="缺少 business_code，且当前存在多个已注册业务",
            data={"available_businesses": list(async_skill_agents.keys())}
        )

    agent = async_skill_agents.get(resolved_business_code)
    if not agent:
        raise SkillNotFoundError(
            message=f"业务代码未找到: {resolved_business_code}",
            data={"business_code": resolved_business_code}
        )

    context = {
        "operator": _normalize_operator(operator, source),
        "operator_source": source,
        "env": "uat"
    }
    if session_id:
        context["session_id"] = session_id

    user_input = message.strip()
    _cleanup_expired_session_memory()
    session_key = _get_session_key(
        business_code=resolved_business_code,
        session_id=session_id,
        operator=context.get("operator"),
        source=source
    )
    memory = session_memory_store.get(session_key)
    pending_execute = memory.get("pending_execute") if memory else None
    if pending_execute:
        if _is_execute_cancel(user_input):
            memory.pop("pending_execute", None)
            session_memory_store[session_key] = memory
            return SkillResponse(
                success=False,
                message="已取消本次待执行操作。",
                data={"pending_execute": False},
                error=None,
                intent=None,
                params=None,
                skill_name=pending_execute.get("skill_name")
            )
        if _is_execute_confirm(user_input):
            user_input = pending_execute.get("composed_input") or pending_execute.get("base_input")
            context["execute_confirmed"] = True
            memory.pop("pending_execute", None)
            session_memory_store[session_key] = memory
        else:
            composed_input = f"{pending_execute.get('base_input', '')}，{user_input}".strip("，")
            pending_execute["composed_input"] = composed_input
            pending_execute["updated_at"] = int(time.time())
            memory["pending_execute"] = pending_execute
            session_memory_store[session_key] = memory
            return SkillResponse(
                success=False,
                message="已记录补充参数。请回复“确认执行”继续，或回复“取消”放弃。",
                data={
                    "pending_execute": True,
                    "skill_name": pending_execute.get("skill_name"),
                    "composed_input": composed_input
                },
                error=None,
                intent=None,
                params=None,
                skill_name=pending_execute.get("skill_name")
            )

    result = await agent.process(user_input, context)
    if result.get("status") == "blocked" and (result.get("data") or {}).get("pending_execute"):
        session_memory_store[session_key] = {
            "updated_at": time.time(),
            "turns": [],
            "pending_execute": {
                "skill_name": result.get("skill_name"),
                "base_input": user_input,
                "composed_input": user_input,
                "created_at": int(time.time()),
                "updated_at": int(time.time())
            }
        }
    result = _append_business_hints(result, user_input=user_input, business_code=resolved_business_code)
    return SkillResponse(
        success=result.get("success", False),
        data=result.get("data"),
        message=MessageFormatter.sanitize_error_message(result.get("message")),
        error=result.get("error"),
        intent=result.get("intent"),
        params=result.get("params"),
        skill_name=result.get("skill_name")
    )


@app.post("/agent/langgraph/execute", response_model=SkillResponse)
async def execute_langgraph_agent(request: LangGraphAgentRequest):
    """LangGraph architecture entry point for gradual migration."""
    from agent_core.langgraph_agent import LangGraphAgent

    context = request.context or {}
    env = context.get("env", "uat")
    if env != "uat":
        raise EnvNotAllowedError(
            message=f"系统仅支持 UAT 环境，当前环境: {env}。生产环境操作已被禁止。",
            data={"env": env, "allowed_env": "uat"}
        )
    context["env"] = "uat"
    context["operator"] = _normalize_operator(context.get("operator"), context.get("operator_source"))

    agent = LangGraphAgent()
    result = await agent.ainvoke(request.user_input, context=context)
    return SkillResponse(
        success=result.get("success", False),
        code=result.get("code"),
        data=result.get("data"),
        message=MessageFormatter.sanitize_error_message(result.get("message")),
        error=result.get("error"),
        intent=result.get("intent"),
        params=result.get("params"),
        skill_name=result.get("tool_name") or result.get("skill_name"),
        request_id=result.get("request_id"),
    )


@app.post("/agent/execute", response_model=SkillResponse)
async def execute_agent(request: Request):
    """
    执行Agent - LLM全流程驱动（异步版本）
    
    支持两种请求格式：
    1. 标准格式：{"business_code": "...", "user_input": "..."}
    2. 工作流格式：{"message": "..."}
    
    1. LLM意图识别
    2. LLM参数提取
    3. 参数适配（格式/别名/指代）
    4. 调用Skill执行
    """
    # 解析请求体
    body = await request.json()
    
    # 判断请求格式
    if "message" in body:
        # 工作流平台格式
        user_input = body.get("message", "").strip()
        business_code = body.get("business_code")
        source = body.get("source", "workflow")
        operator = _normalize_operator(body.get("operator"), source)
        context = {
            "operator": operator,
            "operator_source": source,
            "env": body.get("env", "uat")
        }
        logger.info(f"工作流平台请求 - message: {user_input}")
    elif "user_input" in body:
        # 标准格式
        user_input = body.get("user_input", "").strip()
        business_code = body.get("business_code")
        context = body.get("context")
        source = body.get("source") or (context or {}).get("source") or (context or {}).get("operator_source")
        operator = body.get("operator") or (context or {}).get("operator")
        logger.info(f"标准请求 - user_input: {user_input}")
    else:
        # 格式错误
        raise HTTPException(
            status_code=422,
            detail="请求参数错误：需要 'message' 或 'user_input' 字段"
        )

    business_code = business_code or _get_default_business_code()
    if not business_code:
        raise BusinessError(
            code=ErrorCode.INVALID_PARAM,
            message="缺少 business_code，且当前存在多个已注册业务",
            data={"available_businesses": list(async_skill_agents.keys())}
        )

    # 环境检查：强制 UAT
    env = (context or {}).get("env", "uat")
    if env != "uat":
        raise EnvNotAllowedError(
            message=f"系统仅支持 UAT 环境，当前环境: {env}。生产环境操作已被禁止。",
            data={"env": env, "allowed_env": "uat"}
        )
    if context is None:
        context = {}
    context["operator"] = _normalize_operator(context.get("operator") or operator, context.get("operator_source") or source)
    if source:
        context["operator_source"] = source
    context["env"] = "uat"
    if body.get("session_id"):
        context["session_id"] = body.get("session_id")

    # 会话记忆：注入 history，并支持补参短句继承上一轮指令
    _cleanup_expired_session_memory()
    session_id = context.get("session_id")
    session_key = _get_session_key(
        business_code=business_code,
        session_id=session_id,
        operator=context.get("operator"),
        source=context.get("operator_source")
    )
    memory = session_memory_store.get(session_key)
    pending_execute = memory.get("pending_execute") if memory else None
    if pending_execute:
        if _is_execute_cancel(user_input):
            memory.pop("pending_execute", None)
            session_memory_store[session_key] = memory
            return SkillResponse(
                success=False,
                message=MessageFormatter.sanitize_error_message("已取消本次待执行操作。"),
                data={"pending_execute": False},
                error=None,
                intent=None,
                params=None,
                skill_name=pending_execute.get("skill_name")
            )
        if _is_execute_confirm(user_input):
            user_input = pending_execute.get("composed_input") or pending_execute.get("base_input")
            context["execute_confirmed"] = True
            logger.info(f"收到执行确认，继续执行待处理指令: session_key={session_key}")
            memory.pop("pending_execute", None)
            session_memory_store[session_key] = memory
        else:
            composed_input = f"{pending_execute.get('base_input', '')}，{user_input}".strip("，")
            pending_execute["composed_input"] = composed_input
            pending_execute["updated_at"] = int(time.time())
            memory["pending_execute"] = pending_execute
            session_memory_store[session_key] = memory
            return SkillResponse(
                success=False,
                message=(
                    "已记录补充参数。为避免误操作，请回复“确认执行”继续，"
                    "或回复“取消”放弃本次执行。"
                ),
                data={
                    "pending_execute": True,
                    "skill_name": pending_execute.get("skill_name"),
                    "composed_input": composed_input
                },
                error=None,
                intent=None,
                params=None,
                skill_name=pending_execute.get("skill_name")
            )

    if memory:
        context["history"] = list(memory.get("turns", []))
        last_turn = context["history"][-1] if context["history"] else {}
        if _is_param_only_followup(user_input) and last_turn.get("user_input"):
            user_input = f"{last_turn['user_input']}，{user_input}"
            logger.info(f"检测到补参短句，继承上轮指令: session_key={session_key}")
    
    # 获取对应业务的AsyncSkillAgent（使用异步版本）
    agent = async_skill_agents.get(business_code)
    if not agent:
        # 抛出统一异常
        raise SkillNotFoundError(
            message=f"业务代码未找到: {business_code}",
            data={"business_code": business_code}
        )
    
    # 异步处理请求
    result = await agent.process(user_input, context)
    result = _append_business_hints(result, user_input=user_input, business_code=business_code)

    # 更新会话记忆（默认保留最近5轮、10分钟过期）
    intent = result.get("intent") or {}
    params = result.get("params") or {}
    skill_name = result.get("skill_name")
    if skill_name and skill_name != "unknown":
        turns = deque(maxlen=SESSION_MAX_TURNS)
        if memory and isinstance(memory.get("turns"), list):
            for item in memory["turns"][-SESSION_MAX_TURNS:]:
                turns.append(item)
        turns.append({
            "user_input": user_input,
            "skill_name": skill_name,
            "intent": {
                "skill_name": intent.get("skill_name"),
                "confidence": intent.get("confidence"),
                "skill_type": intent.get("skill_type")
            },
            "params": params,
            "timestamp": int(time.time())
        })
        session_memory_store[session_key] = {
            "updated_at": time.time(),
            "turns": list(turns),
            "pending_execute": memory.get("pending_execute") if memory else None
        }

    # 执行类被拦截时，进入“待补参/待确认”状态
    intent_info = result.get("intent") or {}
    is_execute_blocked = (
        result.get("success") is False and
        intent_info.get("skill_type") == "execute" and
        result.get("skill_name") and
        result.get("skill_name") != "unknown"
    )
    if is_execute_blocked:
        current_memory = session_memory_store.get(session_key, {"updated_at": time.time(), "turns": []})
        current_memory["pending_execute"] = {
            "skill_name": result.get("skill_name"),
            "base_input": user_input,
            "composed_input": user_input,
            "created_at": int(time.time()),
            "updated_at": int(time.time())
        }
        current_memory["updated_at"] = time.time()
        session_memory_store[session_key] = current_memory
        extra_tips = (
            "\n\n你可以继续两种方式：\n"
            "1) 补充参数（例如：用户id:9075566）\n"
            "2) 直接发送完整指令（例如：给用户9075566发礼物20123到专属tab）\n"
            "补参后请回复“确认执行”，或回复“取消”放弃本次执行。"
        )
        result["message"] = f"{result.get('message', '')}{extra_tips}"
        if isinstance(result.get("data"), dict):
            result["data"]["pending_execute"] = True
            result["data"]["pending_skill"] = result.get("skill_name")
        elif result.get("data") is None:
            result["data"] = {
                "pending_execute": True,
                "pending_skill": result.get("skill_name")
            }

    return SkillResponse(
        success=result.get("success", False),
        data=result.get("data"),
        message=MessageFormatter.sanitize_error_message(result.get("message")),
        error=result.get("error"),
        intent=result.get("intent"),
        params=result.get("params"),
        skill_name=result.get("skill_name")
    )


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "framework": "AI测试助手HTTP网关",
        "businesses": list(skill_agents.keys()),
        "skills_registered": len(skill_core.skills) if skill_core else 0
    }


@app.get("/metrics")
async def metrics():
    """获取性能指标"""
    return get_metrics()


@app.post("/admin/reload_config")
async def reload_config():
    """手动重新加载配置"""
    try:
        from utils.config_watcher import reload_all_configs
        reload_all_configs()
        return {
            "success": True,
            "message": "配置已重新加载"
        }
    except Exception as e:
        logger.error(f"配置重载失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"配置重载失败: {str(e)}"
        }


@app.post("/admin/set_log_level")
async def set_log_level_endpoint(level: str):
    """动态设置日志级别"""
    try:
        from utils.logging_config import set_log_level
        set_log_level(level)
        return {
            "success": True,
            "message": f"日志级别已设置为: {level}"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"设置失败: {str(e)}"
        }


@app.get("/admin/cache/stats")
async def get_cache_stats():
    """获取缓存统计"""
    if cache_manager:
        return {
            "success": True,
            "stats": cache_manager.get_stats()
        }
    return {
        "success": False,
        "message": "缓存管理器未初始化"
    }


@app.post("/admin/cache/clear")
async def clear_cache(pattern: Optional[str] = None):
    """清空缓存（已禁用Redis清除操作）"""
    return {
        "success": False,
        "message": "缓存清除功能已禁用，避免误操作Redis数据",
        "note": "如需清除缓存，请重启服务"
    }


@app.get("/admin/tasks")
async def get_all_tasks():
    """获取所有异步任务状态"""
    if task_queue:
        return {
            "success": True,
            "tasks": task_queue.get_all_tasks()
        }
    return {
        "success": False,
        "message": "异步任务队列未初始化"
    }


@app.get("/admin/tasks/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    if task_queue:
        status = task_queue.get_task_status(task_id)
        return {
            "success": True,
            "task": status
        }
    return {
        "success": False,
        "message": "异步任务队列未初始化"
    }


@app.post("/debug/capture")
async def capture_request(request: Request):
    """
    调试接口：捕获原始请求
    用于查看工作流平台发送的实际请求格式
    """
    try:
        # 获取原始请求体
        body = await request.body()
        body_str = body.decode('utf-8')
        
        # 尝试解析为 JSON
        try:
            import json
            body_json = json.loads(body_str)
        except:
            body_json = None
        
        # 获取请求头
        headers = dict(request.headers)
        
        # 记录到日志
        logger.info("=" * 60)
        logger.info("捕获到请求:")
        logger.info(f"Method: {request.method}")
        logger.info(f"URL: {request.url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Body (raw): {body_str}")
        logger.info(f"Body (json): {body_json}")
        logger.info("=" * 60)
        
        return {
            "success": True,
            "message": "请求已捕获，请查看服务器日志",
            "captured": {
                "method": request.method,
                "url": str(request.url),
                "headers": headers,
                "body_raw": body_str,
                "body_json": body_json,
                "content_type": headers.get("content-type"),
                "content_length": headers.get("content-length")
            }
        }
    except Exception as e:
        logger.error(f"捕获请求失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": "请求捕获失败，请查看服务日志"
        }


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "AI测试助手HTTP网关",
        "version": "1.4.0",
        "description": "适配企微→工作流→公网代理→内网UAT的HTTP入口（支持异步LLM、缓存和热更新）",
        "endpoints": {
            "business_execute": "/api/{business_code}/skill/execute",
            "legacy_testops": "/api/testops/skill/execute",
            "execute": "/agent/execute",
            "health": "/health",
            "metrics": "/metrics",
            "reload_config": "/admin/reload_config",
            "set_log_level": "/admin/set_log_level",
            "cache_stats": "/admin/cache/stats",
            "cache_clear": "/admin/cache/clear",
            "tasks": "/admin/tasks",
            "task_status": "/admin/tasks/{task_id}",
            "debug_capture": "/debug/capture",
            "docs": "/docs"
        },
        "features": {
            "async_llm": True,
            "intent_cache": True,
            "config_cache": True,
            "cache": cache_manager is not None,
            "async_tasks": task_queue is not None,
            "config_hot_reload": True,
            "metrics": True,
            "logging": True
        },
        "performance": {
            "intent_cache_speedup": "10-150x",
            "config_cache_speedup": "260x",
            "async_llm_concurrency": "2-3x"
        }
    }
