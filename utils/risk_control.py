"""
风险控制工具模块

提供操作人权限校验、操作日志记录等风险控制功能。
"""
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from utils.config_loader import ConfigLoader


logger = logging.getLogger(__name__)

# 简化版操作日志（内存存储，可扩展到数据库）
operation_logs: Dict[str, Dict[str, Any]] = {}


def _get_operator_auth_config() -> Dict[str, Any]:
    """
    获取操作人权限配置

    配置示例：
    {
      "mode": "allow_all" | "whitelist",
      "default_operator": "ear_agent/test_user"
    }
    """
    try:
        framework_cfg = ConfigLoader.load_framework_config("agent_config.json")
        operator_auth = framework_cfg.get("operator_auth", {})
        if not isinstance(operator_auth, dict):
            return {"mode": "allow_all", "default_operator": "ear_agent/test_user"}
        return {
            "mode": operator_auth.get("mode", "allow_all"),
            "default_operator": operator_auth.get("default_operator", "ear_agent/test_user")
        }
    except Exception as e:
        logger.warning(f"加载操作人权限配置失败，默认放行: {e}")
        return {"mode": "allow_all", "default_operator": "ear_agent/test_user"}


def check_operator_permission(
    operator: str,
    whitelist: list,
    skill_id: str
) -> tuple[bool, str]:
    """
    检查操作人权限
    
    Args:
        operator: 操作人账号
        whitelist: 操作人白名单
        skill_id: Skill ID
        
    Returns:
        (是否有权限, 提示信息)
    """
    auth_cfg = _get_operator_auth_config()
    mode = auth_cfg.get("mode", "allow_all")

    if mode == "allow_all":
        return True, "操作人权限模式为 allow_all，默认放行"

    # whitelist 模式：按技能白名单校验
    if not whitelist:
        # 无白名单限制，默认通过
        return True, "无白名单限制"
    
    if operator in whitelist:
        return True, "权限校验通过"
    
    return False, f"操作人 {operator} 无权限执行 {skill_id}"


def record_operation_log(
    operator: str,
    skill_id: str,
    params: Dict[str, Any],
    env: str,
    result: str,
    risk_level: str = "low"
) -> str:
    """
    记录操作日志
    
    Args:
        operator: 操作人账号
        skill_id: Skill ID
        params: 操作参数
        env: 执行环境
        result: 执行结果
        risk_level: 风险等级
        
    Returns:
        操作日志ID
    """
    import time
    log_id = f"LOG-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_entry = {
        "log_id": log_id,
        "timestamp": timestamp,
        "operator": operator,
        "skill_id": skill_id,
        "params": params,
        "env": env,
        "result": result,
        "risk_level": risk_level
    }
    
    # 存储到内存（可扩展到数据库）
    operation_logs[log_id] = log_entry
    
    # 记录到日志
    logger.info(
        f"操作日志 - ID: {log_id}, "
        f"操作人: {operator}, "
        f"Skill: {skill_id}, "
        f"环境: {env}, "
        f"风险等级: {risk_level}, "
        f"参数: {params}, "
        f"结果: {result}"
    )
    
    return log_id


def get_operation_log(log_id: str) -> Dict[str, Any]:
    """
    查询操作日志
    
    Args:
        log_id: 操作日志ID
        
    Returns:
        操作日志详情
    """
    return operation_logs.get(log_id, {})


def check_env_risk(env: str, risk_level: str, skill_type: str = "execute") -> tuple[bool, str]:
    """
    检查环境风险
    
    Args:
        env: 执行环境（uat/prod）
        risk_level: 风险等级（low/medium/high）
        skill_type: Skill 类型（query/execute/analysis）
        
    Returns:
        (是否允许, 提示信息)
    """
    # 通用限制：生产环境禁止所有执行类操作
    if env == "prod" and skill_type == "execute":
        return False, "生产环境禁止执行所有执行类操作，请在 UAT 环境测试"
    
    # 生产环境禁止高风险操作（额外保护）
    if env == "prod" and risk_level == "high":
        return False, "生产环境禁止执行高风险操作"
    
    # 生产环境中风险操作需要特别关注
    if env == "prod" and risk_level == "medium":
        logger.warning(f"生产环境执行中风险操作，需要特别关注")
    
    return True, "环境风险检查通过"


def validate_param_whitelist(
    param_name: str,
    param_value: Any,
    whitelist: list
) -> tuple[bool, str]:
    """
    校验参数白名单
    
    Args:
        param_name: 参数名
        param_value: 参数值
        whitelist: 白名单列表
        
    Returns:
        (是否通过, 提示信息)
    """
    if not whitelist:
        return True, "无白名单限制"
    
    if param_value in whitelist:
        return True, "参数白名单校验通过"
    
    return False, f"参数 {param_name} 值 {param_value} 不在白名单内"


def validate_param_range(
    param_name: str,
    param_value: Any,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None
) -> tuple[bool, str]:
    """
    校验参数范围
    
    Args:
        param_name: 参数名
        param_value: 参数值
        min_value: 最小值
        max_value: 最大值
        
    Returns:
        (是否通过, 提示信息)
    """
    try:
        value = int(param_value)
        
        if min_value is not None and value < min_value:
            return False, f"参数 {param_name} 值 {value} 小于最小值 {min_value}"
        
        if max_value is not None and value > max_value:
            return False, f"参数 {param_name} 值 {value} 超过最大值 {max_value}"
        
        return True, "参数范围校验通过"
        
    except (ValueError, TypeError):
        return False, f"参数 {param_name} 值 {param_value} 不是有效的数值"


def check_sensitive_params(
    params: Dict[str, Any],
    sensitive_params: list
) -> list[str]:
    """
    检查敏感参数
    
    Args:
        params: 参数字典
        sensitive_params: 敏感参数列表
        
    Returns:
        敏感参数警告列表
    """
    warnings = []
    
    for param_name in sensitive_params:
        if param_name in params:
            param_value = params[param_name]
            warnings.append(f"敏感参数 {param_name}={param_value}")
    
    if warnings:
        logger.warning(f"检测到敏感参数: {', '.join(warnings)}")
    
    return warnings
