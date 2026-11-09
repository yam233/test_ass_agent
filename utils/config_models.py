"""
配置验证模型（Pydantic）

用于验证配置文件的结构和数据类型
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, validator


# ============ Skill 配置模型 ============

class SkillParamSchema(BaseModel):
    """Skill 参数 Schema"""
    name: str
    type: str
    required: bool = False
    description: Optional[str] = None
    default: Optional[Any] = None


class SkillMetadata(BaseModel):
    """Skill 元数据"""
    skill_name: str
    description: str
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    author: Optional[str] = None


class SkillConfig(BaseModel):
    """单个 Skill 配置"""
    skill_name: str
    display_name: Optional[str] = None
    description: str
    skill_type: Optional[str] = None
    server_name: Optional[str] = None
    tool_name: Optional[str] = None
    priority: Optional[int] = None
    match_keywords: List[str] = Field(default_factory=list)
    match_entities: List[str] = Field(default_factory=list)
    param_schema: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    
    # 兼容旧格式
    skill_class: Optional[str] = None
    category: Optional[str] = None
    params_schema: Optional[List[SkillParamSchema]] = None
    metadata: Optional[SkillMetadata] = None


class SkillsRegistryConfig(BaseModel):
    """Skills 注册表配置"""
    skills: List[SkillConfig]
    
    @validator('skills')
    def validate_unique_skill_names(cls, v):
        """验证 Skill 名称唯一性"""
        skill_names = [skill.skill_name for skill in v]
        if len(skill_names) != len(set(skill_names)):
            raise ValueError("Skill 名称必须唯一")
        return v


# ============ LLM Prompt 配置模型 ============

class LLMPromptConfig(BaseModel):
    """LLM Prompt 配置"""
    intent_recognition: Optional[str] = None
    parameter_extraction: Optional[str] = None
    response_generation: Optional[str] = None
    error_handling: Optional[str] = None


# ============ 参数规则配置模型 ============

class ParamAliasRule(BaseModel):
    """参数别名规则"""
    param_name: str
    aliases: List[str]


class ParamFormatRule(BaseModel):
    """参数格式规则"""
    param_name: str
    format_type: str
    pattern: Optional[str] = None


class ParamReferenceRule(BaseModel):
    """参数指代规则"""
    param_name: str
    reference_patterns: List[str]


class ParamRulesConfig(BaseModel):
    """参数规则配置"""
    alias_rules: List[ParamAliasRule] = Field(default_factory=list)
    format_rules: List[ParamFormatRule] = Field(default_factory=list)
    reference_rules: List[ParamReferenceRule] = Field(default_factory=list)


# ============ MCP 配置模型 ============

class MCPServerConfig(BaseModel):
    """MCP Server 配置"""
    name: str
    url: str
    timeout: int = 30
    retry: int = 3
    enabled: bool = True


class MCPRegistryConfig(BaseModel):
    """MCP 注册表配置"""
    servers: List[MCPServerConfig]
    
    @validator('servers')
    def validate_unique_server_names(cls, v):
        """验证 Server 名称唯一性"""
        server_names = [server.name for server in v]
        if len(server_names) != len(set(server_names)):
            raise ValueError("MCP Server 名称必须唯一")
        return v


# ============ 框架配置模型 ============

class LLMConfig(BaseModel):
    """LLM 配置"""
    type: str = "openai"
    api_key: str
    model: str
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: int = 30


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8002
    env: str = "uat"
    debug: bool = False


class AgentConfig(BaseModel):
    """Agent 配置"""
    llm: LLMConfig
    server: ServerConfig
    cache_ttl: int = 300
    max_retries: int = 3


# ============ 风险控制配置模型 ============

class EnvRestriction(BaseModel):
    """环境限制规则"""
    env: str
    allowed_operations: List[str]
    blocked_operations: List[str] = Field(default_factory=list)


class RiskControlConfig(BaseModel):
    """风险控制配置"""
    env_restrictions: List[EnvRestriction]
    max_batch_size: int = 100
    rate_limit: Optional[int] = None
    
    @validator('env_restrictions')
    def validate_unique_envs(cls, v):
        """验证环境名称唯一性"""
        envs = [rule.env for rule in v]
        if len(envs) != len(set(envs)):
            raise ValueError("环境名称必须唯一")
        return v


# ============ 回复规则配置模型 ============

class ReplyTemplate(BaseModel):
    """回复模板"""
    template_name: str
    template: str
    variables: List[str] = Field(default_factory=list)


class ReplyRulesConfig(BaseModel):
    """回复规则配置"""
    templates: List[ReplyTemplate]
    default_template: Optional[str] = None
    
    @validator('templates')
    def validate_unique_template_names(cls, v):
        """验证模板名称唯一性"""
        template_names = [t.template_name for t in v]
        if len(template_names) != len(set(template_names)):
            raise ValueError("模板名称必须唯一")
        return v
