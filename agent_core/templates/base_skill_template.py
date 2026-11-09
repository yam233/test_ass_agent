"""
Skill 基础模板

所有业务 Skill 必须继承此基类，实现模板化开发。

设计原则：
1. 模板化实现：业务 Skill 只需实现 execute() 核心方法
2. 自动复用：参数校验、日志、异常处理、风险控制等通用逻辑自动处理
3. 统一协议：输入输出遵循 SkillInput/SkillOutput 协议
4. 风险控制：执行类 Skill 自动进行风险控制检查

使用方式：
```python
class MySkill(BaseSkillTemplate):
    def execute(self, skill_input: SkillInput) -> SkillOutput:
        # 实现业务逻辑
        return SkillOutput(code=0, msg="成功", data={...})
    
    def get_param_schema(self) -> dict:
        # 返回参数定义
        return {...}
```
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
import time
import json
import os
from agent_core.protocol import SkillInput, SkillOutput, SkillType, RiskControlConfig
from utils.risk_control import (
    check_operator_permission,
    record_operation_log,
    check_env_risk,
    validate_param_whitelist,
    validate_param_range,
    check_sensitive_params
)


class BaseSkillTemplate(ABC):
    """
    Skill 基础模板类
    
    所有业务 Skill 必须继承此类，提供统一的接口和通用逻辑。
    
    Attributes:
        skill_name: Skill 名称
        skill_type: Skill 类型（query/execute/analysis）
        business_code: 业务代码
        logger: 日志记录器
        risk_config: 风险控制配置
        metadata_config: 元数据配置
    """
    
    def __init__(self, skill_name: str, skill_type: str, business_code: str = "testops"):
        """
        初始化 Skill
        
        Args:
            skill_name: Skill 名称
            skill_type: Skill 类型
            business_code: 业务代码
        """
        self.skill_name = skill_name
        self.skill_type = skill_type
        self.business_code = business_code
        self.logger = logging.getLogger(f"skill.{skill_name}")
        
        # 加载元数据配置
        self.metadata_config = self._load_metadata()
        
        # 加载风险控制配置
        self.risk_config = self._load_risk_config()
    
    def _load_metadata(self) -> Dict[str, Any]:
        """加载 Skill 元数据配置（全局 + 业务覆盖，兼容旧路径）。"""
        def _load_json_if_exists(path: str) -> Dict[str, Any]:
            if not os.path.exists(path):
                return {}
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}

        def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
            merged = dict(base)
            for key, value in override.items():
                if (
                    key in merged and
                    isinstance(merged[key], dict) and
                    isinstance(value, dict)
                ):
                    merged[key] = _deep_merge(merged[key], value)
                else:
                    merged[key] = value
            return merged

        try:
            global_manifest_path = f"config/skill_manifest/{self.skill_name}.json"
            # 兼容旧结构：当前仓库主要使用该路径
            legacy_business_manifest_path = f"config/business/{self.business_code}/manifest/{self.skill_name}.json"
            business_override_path = (
                f"config/business/{self.business_code}/skill_manifest_override/{self.skill_name}.json"
            )

            metadata = _load_json_if_exists(global_manifest_path)
            metadata = _deep_merge(metadata, _load_json_if_exists(legacy_business_manifest_path))
            metadata = _deep_merge(metadata, _load_json_if_exists(business_override_path))
            return metadata
        except Exception as e:
            self.logger.warning(f"加载元数据配置失败: {e}")
        return {}
    
    def _load_risk_config(self) -> RiskControlConfig:
        """加载风险控制配置"""
        risk_config_data = self.metadata_config.get("risk_control", {})
        return RiskControlConfig(**risk_config_data)
    
    
    def pre_check(self, skill_input: SkillInput) -> tuple[bool, str]:
        """
        执行类 Skill 前置风险控制检查
        
        检查项：
        1. 操作人权限校验
        2. 参数白名单/范围校验
        3. 环境风险校验
        4. 敏感参数检查
        
        Args:
            skill_input: Skill 输入
            
        Returns:
            (是否通过, 提示信息)
        """
        # 1. 操作人权限校验
        if self.risk_config.operator_whitelist:
            has_permission, msg = check_operator_permission(
                skill_input.operator,
                self.risk_config.operator_whitelist,
                self.skill_name
            )
            if not has_permission:
                return False, msg
        
        # 2. 参数白名单/范围校验
        input_params = self.metadata_config.get("input_parameters", [])
        for param_def in input_params:
            param_name = param_def.get("name")
            param_value = skill_input.params.get(param_name)
            
            if param_value is None:
                continue
            
            # 白名单校验
            if "whitelist" in param_def.get("validation", {}):
                whitelist = param_def["validation"]["whitelist"]
                is_valid, msg = validate_param_whitelist(param_name, param_value, whitelist)
                if not is_valid:
                    return False, msg
            
            # 数值范围校验
            validation = param_def.get("validation", {})
            if "min" in validation or "max" in validation:
                is_valid, msg = validate_param_range(
                    param_name,
                    param_value,
                    validation.get("min"),
                    validation.get("max")
                )
                if not is_valid:
                    return False, msg
        
        # 3. 环境风险校验
        is_safe, msg = check_env_risk(
            skill_input.env,
            self.risk_config.risk_level.value,
            self.skill_type
        )
        if not is_safe:
            return False, msg
        
        # 4. 敏感参数检查
        if self.risk_config.sensitive_params:
            warnings = check_sensitive_params(
                skill_input.params,
                self.risk_config.sensitive_params
            )
            if warnings:
                self.logger.warning(f"敏感参数检测: {', '.join(warnings)}")
        
        return True, "前置风险控制检查通过"
    
    def __call__(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行 Skill（带通用逻辑）
        
        自动处理：
        1. 参数校验
        2. 风险控制检查（执行类）
        3. 日志记录
        4. 异常处理
        5. 执行时间统计
        6. 操作日志记录
        
        Args:
            skill_input: Skill 输入协议
            
        Returns:
            Skill 输出协议
        """
        start_time = time.time()
        
        try:
            # 1. 参数校验
            validation_result = self.validate_params(skill_input.params)
            if not validation_result["valid"]:
                return SkillOutput(
                    code=400,
                    msg=f"参数校验失败: {', '.join(validation_result['errors'])}",
                    format="json"
                )
            
            # 2. 执行类 Skill 前置风险控制检查
            if self.skill_type == "execute":
                pre_check_passed, pre_check_msg = self.pre_check(skill_input)
                if not pre_check_passed:
                    return SkillOutput(
                        code=403,
                        msg=pre_check_msg,
                        format="json",
                        risk_tips=pre_check_msg
                    )
            
            # 3. 记录日志
            self.logger.info(
                f"执行 Skill: {self.skill_name}, "
                f"操作人: {skill_input.operator}, "
                f"环境: {skill_input.env}, "
                f"参数: {skill_input.params}"
            )
            
            # 4. 执行核心逻辑
            result = self.execute(skill_input)
            
            # 5. 添加元数据
            execution_time = time.time() - start_time
            if result.metadata is None:
                result.metadata = {}
            result.metadata.update({
                "skill_name": self.skill_name,
                "skill_type": self.skill_type,
                "execution_time": f"{execution_time:.3f}s",
                "operator": skill_input.operator,
                "env": skill_input.env
            })
            
            # 6. 记录操作日志（风控要求）
            if self.risk_config.need_log and self.skill_type == "execute":
                log_id = record_operation_log(
                    operator=skill_input.operator,
                    skill_id=self.skill_name,
                    params=skill_input.params,
                    env=skill_input.env,
                    result=result.msg,
                    risk_level=self.risk_config.risk_level.value
                )
                result.operation_log_id = log_id
            
            # 7. 记录结果
            self.logger.info(
                f"Skill 执行完成: {self.skill_name}, "
                f"状态码: {result.code}, "
                f"操作日志ID: {result.operation_log_id}"
            )
            
            return result
            
        except Exception as e:
            # 异常处理
            self.logger.error(f"Skill 执行异常: {self.skill_name}, 错误: {str(e)}", exc_info=True)
            return SkillOutput(
                code=500,
                msg=f"执行异常: {str(e)}",
                format="json",
                risk_tips=f"执行异常: {str(e)}",
                metadata={
                    "skill_name": self.skill_name,
                    "skill_type": self.skill_type,
                    "error_type": type(e).__name__,
                    "operator": skill_input.operator,
                    "env": skill_input.env
                }
            )
    
    @abstractmethod
    def execute(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行 Skill 核心逻辑（子类必须实现）
        
        Args:
            skill_input: Skill 输入协议
            
        Returns:
            Skill 输出协议
            
        Example:
            ```python
            def execute(self, skill_input: SkillInput) -> SkillOutput:
                params = skill_input.params
                # 业务逻辑
                result = do_something(params)
                return SkillOutput(
                    code=0,
                    msg="成功",
                    data=result,
                    format="json"
                )
            ```
        """
        pass
    
    @abstractmethod
    def get_param_schema(self) -> Dict[str, Any]:
        """
        获取参数 Schema（子类必须实现）
        
        Returns:
            参数 Schema 定义
            
        Example:
            ```python
            def get_param_schema(self) -> dict:
                return {
                    "user_id": {
                        "type": "integer",
                        "required": True,
                        "desc": "用户ID"
                    },
                    "gift_id": {
                        "type": "integer",
                        "required": True,
                        "desc": "礼物ID"
                    }
                }
            ```
        """
        pass
    
    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证参数（自动校验，支持增强校验规则）
        
        支持的校验规则：
        - required: 必填参数
        - type: 类型检查（integer/string/array等）
        - enum: 枚举值检查
        - validation.min/max: 数值范围检查
        - validation.pattern: 正则表达式检查
        - alias: 参数别名映射
        
        Args:
            params: 参数字典
            
        Returns:
            验证结果：{"valid": bool, "errors": list}
        """
        import re
        errors = []
        param_schema = self.get_param_schema()
        
        # 1. 处理参数别名映射
        params = self._map_param_aliases(params)
        
        # 2. 检查必填参数
        for param_name, param_def in param_schema.items():
            required = param_def.get("required", False)
            
            # 特殊处理：背包礼物的 gift_id 在有 gift_nums 或 gift_ids 时不是必填
            if param_name == "gift_id" and not required:
                # 如果存在 gift_nums 或 gift_ids，则 gift_id 不是必填
                if "gift_nums" in params or "gift_ids" in params:
                    # 跳过 gift_id 的必填检查
                    continue
            
            if required and param_name not in params:
                errors.append(f"缺少必填参数: {param_name}")
        
        # 3. 检查参数类型和校验规则
        for param_name, value in params.items():
            if param_name in param_schema:
                param_def = param_schema[param_name]
                expected_type = param_def.get("type")
                
                # 3.1 类型检查和转换
                if expected_type == "integer" and not isinstance(value, int):
                    try:
                        params[param_name] = int(value)
                        value = params[param_name]
                    except (ValueError, TypeError):
                        errors.append(f"参数 {param_name} 类型错误，期望: integer")
                        continue
                
                elif expected_type == "string" and not isinstance(value, str):
                    params[param_name] = str(value)
                    value = params[param_name]
                
                # 3.2 枚举值检查
                enum_values = param_def.get("enum")
                if enum_values and value not in enum_values:
                    errors.append(
                        f"参数 {param_name} 值不在允许范围内，"
                        f"允许值: {', '.join(map(str, enum_values))}"
                    )
                
                # 3.3 校验规则检查
                validation = param_def.get("validation", {})
                if validation:
                    # 数值范围检查
                    if "min" in validation and isinstance(value, (int, float)):
                        if value < validation["min"]:
                            msg = validation.get("message", 
                                f"参数 {param_name} 小于最小值 {validation['min']}")
                            errors.append(msg)
                    
                    if "max" in validation and isinstance(value, (int, float)):
                        if value > validation["max"]:
                            msg = validation.get("message",
                                f"参数 {param_name} 大于最大值 {validation['max']}")
                            errors.append(msg)
                    
                    # 正则表达式检查
                    if "pattern" in validation and isinstance(value, str):
                        pattern = validation["pattern"]
                        if not re.match(pattern, str(value)):
                            msg = validation.get("message",
                                f"参数 {param_name} 格式不正确")
                            errors.append(msg)
        
        return {
            "valid": len(errors) == 0,
            "errors": errors
        }
    
    def _map_param_aliases(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        映射参数别名到标准参数名
        
        Args:
            params: 原始参数字典
            
        Returns:
            映射后的参数字典
        """
        param_schema = self.get_param_schema()
        mapped_params = {}
        
        for param_name, value in params.items():
            # 查找是否有标准参数名匹配此别名
            standard_name = param_name
            for schema_name, schema_def in param_schema.items():
                aliases = schema_def.get("alias", [])
                if param_name in aliases or param_name == schema_name:
                    standard_name = schema_name
                    break
            
            mapped_params[standard_name] = value
        
        return mapped_params
