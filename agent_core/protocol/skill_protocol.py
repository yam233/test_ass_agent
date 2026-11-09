"""
Skill 输入/输出统一协议规范

定义标准化的 Skill 接口规范，确保所有 Skill 遵循统一协议。

协议设计原则：
1. 输入协议：SkillInput - 标准化输入参数
2. 输出协议：SkillOutput - 标准化输出格式
3. 类型枚举：SkillType - 定义 Skill 分类
4. 风险控制：RiskControlConfig - 风险控制配置
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from enum import Enum


class SkillType(str, Enum):
    """
    Skill 分类枚举
    
    - QUERY: 查询类 Skill（只读操作，不修改数据）
    - EXECUTE: 操作类 Skill（写操作，修改数据）
    - ANALYSIS: 分析类 Skill（数据分析，后续扩展）
    """
    QUERY = "query"
    EXECUTE = "execute"
    ANALYSIS = "analysis"  # 后续扩展


class RiskLevel(str, Enum):
    """
    风险等级枚举
    
    - LOW: 低风险（查询类操作）
    - MEDIUM: 中风险（普通执行类操作）
    - HIGH: 高风险（批量删除、敏感数据修改）
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskControlConfig(BaseModel):
    """
    风险控制配置
    
    用于执行类 Skill 的风险控制。
    
    Attributes:
        need_log: 是否记录操作日志
        need_confirm: 是否需要二次确认（高风险操作）
        operator_whitelist: 操作人白名单
        risk_level: 风险等级
        sensitive_params: 敏感参数列表
        audit_fields: 审计字段列表
    """
    need_log: bool = Field(default=True, description="是否记录操作日志")
    need_confirm: bool = Field(default=False, description="是否需要二次确认")
    operator_whitelist: List[str] = Field(default_factory=list, description="操作人白名单")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="风险等级")
    sensitive_params: List[str] = Field(default_factory=list, description="敏感参数列表")
    audit_fields: List[str] = Field(default_factory=list, description="审计字段列表")


class SkillInput(BaseModel):
    """
    Skill 输入协议
    
    统一的输入格式，所有 Skill 必须遵循此协议。
    
    Attributes:
        user_input: 用户原始输入
        business_code: 业务代码（如 "ear_test"）
        session_id: 会话ID（用于标识会话）
        params: 提取并适配后的参数字典
        operator: 操作人账号（用于权限校验）
        env: 执行环境（uat/prod）
        context: 上下文信息（会话历史、用户信息等）
        skill_name: Skill 名称
        skill_type: Skill 类型（query/execute/analysis）
    """
    user_input: str = Field(..., description="用户原始输入")
    business_code: str = Field(..., description="业务代码")
    session_id: str = Field(default="", description="会话ID")
    params: Dict[str, Any] = Field(default_factory=dict, description="参数字典")
    operator: str = Field(default="ear_agent/test_user", description="操作人账号")
    env: str = Field(default="uat", description="执行环境：uat/prod")
    context: Dict[str, Any] = Field(default_factory=dict, description="上下文信息")
    skill_name: Optional[str] = Field(default=None, description="Skill名称")
    skill_type: Optional[SkillType] = Field(default=None, description="Skill类型")
    
    @validator("env")
    def env_must_be_valid(cls, v):
        """环境校验"""
        if v not in ["uat", "prod"]:
            raise ValueError("环境仅支持uat/prod")
        return v


class SkillOutput(BaseModel):
    """
    Skill 输出协议
    
    统一的输出格式，所有 Skill 必须遵循此协议。
    
    Attributes:
        code: 状态码（0=成功，非0=失败）
        msg: 消息（成功或失败的描述）
        data: 返回数据（业务数据）
        format: 输出格式（json/markdown/text/wechat_card）
        metadata: 元数据（执行时间、版本等）
        risk_tips: 风险提示信息
        operation_log_id: 操作日志ID
    """
    code: int = Field(default=0, description="状态码，0=成功，非0=失败")
    msg: str = Field(default="", description="消息")
    data: Optional[Any] = Field(default=None, description="返回数据")
    format: str = Field(default="json", description="输出格式：json/markdown/text/wechat_card")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="元数据")
    risk_tips: Optional[str] = Field(default=None, description="风险提示信息")
    operation_log_id: Optional[str] = Field(default=None, description="操作日志ID")
    
    @property
    def success(self) -> bool:
        """是否成功（兼容旧版本）"""
        return self.code == 0
    
    @property
    def message(self) -> str:
        """消息（兼容旧版本）"""
        return self.msg
    
    @property
    def error(self) -> Optional[str]:
        """错误信息（兼容旧版本）"""
        return self.msg if self.code != 0 else None
