"""
审计日志工具

提供关键操作的审计日志记录，支持可追溯性和合规性要求。

设计原则：
1. 独立的审计日志文件（不与应用日志混合）
2. 结构化日志格式（JSON）
3. 记录完整的操作上下文（操作人、时间、参数、结果等）
4. 支持追踪ID（trace_id）
5. 不可篡改（只追加，不修改）
"""
import logging
import logging.handlers
import os
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime

# 审计日志器（独立配置）
_audit_logger: Optional[logging.Logger] = None


def get_audit_logger() -> logging.Logger:
    """
    获取审计日志器
    
    Returns:
        审计日志器实例
    """
    global _audit_logger
    
    if _audit_logger is None:
        # 创建审计日志器
        _audit_logger = logging.getLogger("audit")
        _audit_logger.setLevel(logging.INFO)
        _audit_logger.propagate = False  # 不传播到根日志器
        
        # 创建日志目录
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 文件处理器（带轮转）
        log_path = os.path.join(log_dir, "audit.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=10,  # 保留10个备份
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        
        # JSON 格式化器
        formatter = logging.Formatter('%(message)s')
        file_handler.setFormatter(formatter)
        
        _audit_logger.addHandler(file_handler)
    
    return _audit_logger


def audit_log(
    operator: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error: Optional[str] = None,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    env: str = "uat",
    duration_ms: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None
):
    """
    记录审计日志
    
    Args:
        operator: 操作人（必填）
        action: 操作动作（必填，如：execute_skill、add_gift、query_backpack）
        resource_type: 资源类型（必填，如：skill、gift、user）
        resource_id: 资源ID（可选，如：skill_name、gift_id、user_id）
        params: 操作参数（可选）
        result: 操作结果（可选）
        success: 是否成功（默认 True）
        error: 错误信息（可选）
        trace_id: 追踪ID（可选）
        session_id: 会话ID（可选）
        ip_address: IP地址（可选）
        env: 环境（默认 uat）
        duration_ms: 执行时长（毫秒，可选）
        extra: 额外信息（可选）
    """
    logger = get_audit_logger()
    
    # 构造审计日志数据
    audit_data = {
        "timestamp": datetime.now().isoformat(),
        "timestamp_unix": int(time.time()),
        "operator": operator,
        "action": action,
        "resource_type": resource_type,
        "success": success,
        "env": env
    }
    
    # 添加可选字段
    if resource_id:
        audit_data["resource_id"] = resource_id
    
    if params:
        audit_data["params"] = params
    
    if result:
        audit_data["result"] = result
    
    if error:
        audit_data["error"] = error
    
    if trace_id:
        audit_data["trace_id"] = trace_id
    
    if session_id:
        audit_data["session_id"] = session_id
    
    if ip_address:
        audit_data["ip_address"] = ip_address
    
    if duration_ms is not None:
        audit_data["duration_ms"] = duration_ms
    
    if extra:
        audit_data["extra"] = extra
    
    # 记录日志（JSON 格式）
    logger.info(json.dumps(audit_data, ensure_ascii=False))


def audit_skill_execution(
    operator: str,
    skill_name: str,
    params: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error: Optional[str] = None,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    env: str = "uat",
    duration_ms: Optional[float] = None
):
    """
    记录 Skill 执行审计日志
    
    Args:
        operator: 操作人
        skill_name: Skill 名称
        params: 参数
        result: 结果
        success: 是否成功
        error: 错误信息
        trace_id: 追踪ID
        session_id: 会话ID
        env: 环境
        duration_ms: 执行时长（毫秒）
    """
    audit_log(
        operator=operator,
        action="execute_skill",
        resource_type="skill",
        resource_id=skill_name,
        params=params,
        result=result,
        success=success,
        error=error,
        trace_id=trace_id,
        session_id=session_id,
        env=env,
        duration_ms=duration_ms
    )


def audit_gift_operation(
    operator: str,
    operation: str,  # add/delete/update
    gift_id: str,
    user_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error: Optional[str] = None,
    trace_id: Optional[str] = None,
    env: str = "uat"
):
    """
    记录礼物操作审计日志
    
    Args:
        operator: 操作人
        operation: 操作类型（add/delete/update）
        gift_id: 礼物ID
        user_id: 用户ID
        params: 参数
        result: 结果
        success: 是否成功
        error: 错误信息
        trace_id: 追踪ID
        env: 环境
    """
    action = f"{operation}_gift"
    
    # 合并参数
    full_params = params or {}
    if user_id:
        full_params["user_id"] = user_id
    full_params["gift_id"] = gift_id
    
    audit_log(
        operator=operator,
        action=action,
        resource_type="gift",
        resource_id=gift_id,
        params=full_params,
        result=result,
        success=success,
        error=error,
        trace_id=trace_id,
        env=env
    )


def audit_config_change(
    operator: str,
    config_type: str,  # skill/intent/param/llm
    config_name: str,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
    success: bool = True,
    error: Optional[str] = None,
    trace_id: Optional[str] = None,
    env: str = "uat"
):
    """
    记录配置变更审计日志
    
    Args:
        operator: 操作人
        config_type: 配置类型（skill/intent/param/llm）
        config_name: 配置名称
        old_value: 旧值
        new_value: 新值
        success: 是否成功
        error: 错误信息
        trace_id: 追踪ID
        env: 环境
    """
    params = {
        "config_type": config_type,
        "config_name": config_name
    }
    
    if old_value is not None:
        params["old_value"] = old_value
    
    if new_value is not None:
        params["new_value"] = new_value
    
    audit_log(
        operator=operator,
        action="update_config",
        resource_type="config",
        resource_id=config_name,
        params=params,
        success=success,
        error=error,
        trace_id=trace_id,
        env=env
    )


def audit_data_query(
    operator: str,
    query_type: str,  # backpack/gift/user
    query_params: Dict[str, Any],
    result_count: Optional[int] = None,
    success: bool = True,
    error: Optional[str] = None,
    trace_id: Optional[str] = None,
    env: str = "uat",
    duration_ms: Optional[float] = None
):
    """
    记录数据查询审计日志
    
    Args:
        operator: 操作人
        query_type: 查询类型（backpack/gift/user）
        query_params: 查询参数
        result_count: 结果数量
        success: 是否成功
        error: 错误信息
        trace_id: 追踪ID
        env: 环境
        duration_ms: 执行时长（毫秒）
    """
    result = {}
    if result_count is not None:
        result["count"] = result_count
    
    audit_log(
        operator=operator,
        action=f"query_{query_type}",
        resource_type=query_type,
        params=query_params,
        result=result if result else None,
        success=success,
        error=error,
        trace_id=trace_id,
        env=env,
        duration_ms=duration_ms
    )


class AuditContext:
    """
    审计日志上下文管理器
    
    自动记录操作的开始和结束，计算执行时长。
    """
    
    def __init__(
        self,
        operator: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        env: str = "uat"
    ):
        """
        初始化审计上下文
        
        Args:
            operator: 操作人
            action: 操作动作
            resource_type: 资源类型
            resource_id: 资源ID
            params: 操作参数
            trace_id: 追踪ID
            session_id: 会话ID
            env: 环境
        """
        self.operator = operator
        self.action = action
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.params = params
        self.trace_id = trace_id
        self.session_id = session_id
        self.env = env
        self.start_time = None
        self.result = None
    
    def __enter__(self):
        """进入上下文"""
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        duration_ms = (time.time() - self.start_time) * 1000
        
        if exc_type:
            # 发生异常
            audit_log(
                operator=self.operator,
                action=self.action,
                resource_type=self.resource_type,
                resource_id=self.resource_id,
                params=self.params,
                result=None,
                success=False,
                error=str(exc_val),
                trace_id=self.trace_id,
                session_id=self.session_id,
                env=self.env,
                duration_ms=duration_ms
            )
        else:
            # 正常完成
            audit_log(
                operator=self.operator,
                action=self.action,
                resource_type=self.resource_type,
                resource_id=self.resource_id,
                params=self.params,
                result=self.result,
                success=True,
                error=None,
                trace_id=self.trace_id,
                session_id=self.session_id,
                env=self.env,
                duration_ms=duration_ms
            )
    
    def set_result(self, result: Dict[str, Any]):
        """
        设置操作结果
        
        Args:
            result: 操作结果
        """
        self.result = result


def audit_context(
    operator: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    env: str = "uat"
) -> AuditContext:
    """
    创建审计上下文
    
    Args:
        operator: 操作人
        action: 操作动作
        resource_type: 资源类型
        resource_id: 资源ID
        params: 操作参数
        trace_id: 追踪ID
        session_id: 会话ID
        env: 环境
        
    Returns:
        AuditContext 实例
        
    Example:
        with audit_context(
            operator="test01",
            action="execute_skill",
            resource_type="skill",
            resource_id="add_backpack_gift",
            params={"gift_id": 40001}
        ) as ctx:
            # 执行操作
            result = execute_skill()
            ctx.set_result(result)
    """
    return AuditContext(
        operator=operator,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        params=params,
        trace_id=trace_id,
        session_id=session_id,
        env=env
    )
