"""
专属礼物发放 Skill

支持用户专属/直播间专属/随机礼物发放，支持批量发放。

业务规则：
- 礼物ID以2开头：用户专属礼物
- 礼物ID以7开头：直播间专属礼物
- 礼物ID以8开头：随机礼物
- 有效期：1-1000天，1000表示永久有效
- 批量发放：最大100个
"""
from typing import Dict, Any
import json
from agent_core.templates import BaseSkillTemplate
from agent_core.protocol import SkillInput, SkillOutput


class GiftIssueSkill(BaseSkillTemplate):
    """专属礼物发放 Skill"""
    
    def __init__(self, mcp_adapter=None, business_code: str = "testops"):
        """
        初始化
        
        Args:
            mcp_adapter: MCP 适配器实例
        """
        super().__init__(
            skill_name="execute_gift_issue",
            skill_type="execute",
            business_code=business_code
        )
        self.mcp_adapter = mcp_adapter
        
        # 业务规则
        self.gift_type_mapping = {
            "2": "user",
            "7": "room",
            "8": "random"
        }
        self.max_duration_days = 1000
        self.max_batch_count = 100
    
    def execute(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行专属礼物发放
        
        Args:
            skill_input: Skill 输入协议
            
        Returns:
            Skill 输出协议
        """
        # 0. 参数别名映射（在提取参数之前）
        params = self._map_param_aliases(skill_input.params)
        skill_input.params = params  # 更新映射后的参数
        
        # 1. 提取参数
        gift_id = params.get("gift_id")
        target_id = params.get("target_id")
        user_ids = params.get("user_ids", [])
        room_ids = params.get("room_ids", [])
        issue_type = params.get("issue_type", "user")
        duration_days = params.get("duration_days", 7)
        batch_count = params.get("batch_count", 1)
        
        # 2. 判断是批量用户发放还是单用户重复发放
        is_batch_users = len(user_ids) > 0 or len(room_ids) > 0
        
        if is_batch_users:
            # 批量用户发放：给多个用户/直播间各发放一次
            target_ids = user_ids if len(user_ids) > 0 else room_ids
            if len(room_ids) > 0:
                issue_type = "room"
            
            # 参数校验
            validation_result = self._validate_batch_params(
                gift_id, target_ids, issue_type, duration_days
            )
            if not validation_result["valid"]:
                return SkillOutput(
                    code=400,
                    msg=validation_result["error"],
                    format="json"
                )
            
            # 执行批量发放
            try:
                result = self._execute_batch_gift_issue(
                    gift_id, target_ids, issue_type, duration_days
                )
                
                return SkillOutput(
                    code=0,
                    msg=f"批量发放成功：成功{result['success_count']}个，失败{result['failed_count']}个",
                    data=result,
                    format="wechat_card",
                    metadata={
                        "skill_id": "execute_gift_issue",
                        "risk_level": "medium",
                        "operation": "batch_gift_issue",
                        "target_count": len(target_ids)
                    }
                )
            except Exception as e:
                self.logger.error(f"批量礼物发放失败: {str(e)}", exc_info=True)
                error_msg = self._get_error_message(str(e))
                return SkillOutput(
                    code=500,
                    msg=f"批量发放失败: {error_msg}",
                    format="json"
                )
        else:
            # 单用户重复发放：给同一个用户重复发放N次
            # 参数校验（增强校验）
            validation_result = self._validate_business_params(
                gift_id, target_id, issue_type, duration_days, batch_count
            )
            if not validation_result["valid"]:
                return SkillOutput(
                    code=400,
                    msg=validation_result["error"],
                    format="json"
                )
            
            # 自动识别礼物类型
            detected_type = self._detect_gift_type(gift_id)
            if detected_type and detected_type != issue_type:
                self.logger.info(f"自动识别礼物类型: {detected_type}，覆盖用户输入: {issue_type}")
                issue_type = detected_type
            
            # 调用 MCP 服务执行发放
            try:
                result = self._execute_gift_issue(
                    gift_id, target_id, issue_type, duration_days, batch_count
                )
                
                # 格式化返回结果
                return SkillOutput(
                    code=0,
                    msg="发放成功",
                    data=result,
                    format="wechat_card",
                    metadata={
                        "skill_id": "execute_gift_issue",
                        "risk_level": "medium",
                        "operation": "gift_issue",
                        "batch_count": batch_count
                    }
                )
                
            except Exception as e:
                self.logger.error(f"礼物发放失败: {str(e)}", exc_info=True)
                error_msg = self._get_error_message(str(e))
                return SkillOutput(
                    code=500,
                    msg=f"发放失败: {error_msg}",
                    format="json"
                )
    
    
    def _validate_batch_params(
        self, gift_id: int, target_ids: list, issue_type: str, duration_days: int
    ) -> Dict[str, Any]:
        """
        验证批量发放参数
        
        Args:
            gift_id: 礼物ID
            target_ids: 目标ID列表
            issue_type: 发放类型
            duration_days: 有效期天数
            
        Returns:
            验证结果
        """
        # 校验礼物ID
        if not gift_id or gift_id <= 0:
            return {"valid": False, "error": "礼物ID无效"}
        
        # 校验目标ID列表
        if not target_ids or len(target_ids) == 0:
            return {"valid": False, "error": "目标ID列表不能为空"}
        
        if len(target_ids) > 100:
            return {"valid": False, "error": "批量发放最多支持100个目标"}
        
        # 校验每个目标ID
        for target_id in target_ids:
            if not isinstance(target_id, int) or target_id <= 0 or target_id > 99999999:
                return {
                    "valid": False,
                    "error": f"目标ID {target_id} 无效，必须在1-99999999之间"
                }
        
        # 校验有效期
        if duration_days < 1 or duration_days > self.max_duration_days:
            return {
                "valid": False,
                "error": f"有效期必须在1-{self.max_duration_days}天之间"
            }
        
        return {"valid": True}
    
    def _execute_batch_gift_issue(
        self, gift_id: int, target_ids: list, issue_type: str, duration_days: int
    ) -> Dict[str, Any]:
        """
        执行批量礼物发放（给多个用户/直播间各发放一次）
        
        Args:
            gift_id: 礼物ID
            target_ids: 目标ID列表
            issue_type: 发放类型
            duration_days: 有效期天数
            
        Returns:
            发放结果
        """
        if not self.mcp_adapter:
            # 模拟返回（用于测试）
            return {
                "gift_id": gift_id,
                "target_ids": target_ids,
                "issue_type": issue_type,
                "duration_days": duration_days,
                "target_count": len(target_ids),
                "success_count": len(target_ids),
                "failed_count": 0,
                "records": [
                    {
                        "target_id": target_id,
                        "record_id": f"REC-{target_id}",
                        "status": "success"
                    }
                    for target_id in target_ids
                ]
            }
        
        # 根据发放类型选择对应的 MCP 工具
        tool_mapping = {
            "user": "add_gift_to_user",
            "room": "add_gift_to_room",
            "random": "add_random_gift"
        }
        tool_name = tool_mapping.get(issue_type, "add_gift_to_user")
        
        # 批量发放给多个目标
        results = []
        for target_id in target_ids:
            try:
                result = self.mcp_adapter.call(
                    server_name="gift-management-server",
                    tool_name=tool_name,
                    params={
                        "gift_id": gift_id,
                        "target_id": target_id,
                        "duration_days": duration_days
                    }
                )
                results.append({
                    "target_id": target_id,
                    "status": "success",
                    "result": result
                })
                self.logger.info(f"✓ 成功发放礼物 {gift_id} 给目标 {target_id}")
            except Exception as e:
                results.append({
                    "target_id": target_id,
                    "status": "failed",
                    "error": str(e)
                })
                self.logger.error(f"✗ 发放礼物 {gift_id} 给目标 {target_id} 失败: {e}")
        
        # 统计结果
        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = len(target_ids) - success_count
        
        return {
            "gift_id": gift_id,
            "target_ids": target_ids,
            "issue_type": issue_type,
            "duration_days": duration_days,
            "target_count": len(target_ids),
            "success_count": success_count,
            "failed_count": failed_count,
            "records": results
        }
    
    def _validate_business_params(
        self, gift_id: int, target_id: int, issue_type: str,
        duration_days: int, batch_count: int
    ) -> Dict[str, Any]:
        """
        业务参数校验
        
        Args:
            gift_id: 礼物ID
            target_id: 目标ID
            issue_type: 发放类型
            duration_days: 有效期天数
            batch_count: 批量数量
            
        Returns:
            校验结果
        """
        # 校验礼物ID格式
        gift_id_str = str(gift_id)
        if not gift_id_str[0] in ["2", "7", "8"]:
            return {
                "valid": False,
                "error": "礼物ID必须以2/7/8开头（2=用户专属，7=直播间专属，8=随机礼物）"
            }
        
        # 校验目标ID范围
        if target_id < 1 or target_id > 99999999:
            return {
                "valid": False,
                "error": "目标ID必须在1-99999999之间"
            }
        
        # 校验发放类型
        if issue_type not in ["user", "room", "random"]:
            return {
                "valid": False,
                "error": "发放类型必须是 user/room/random"
            }
        
        # 校验有效期
        if duration_days < 1 or duration_days > self.max_duration_days:
            return {
                "valid": False,
                "error": f"有效期必须在1-{self.max_duration_days}天之间"
            }
        
        # 校验批量数量
        if batch_count < 1 or batch_count > self.max_batch_count:
            return {
                "valid": False,
                "error": f"批量数量必须在1-{self.max_batch_count}之间"
            }
        
        return {"valid": True}
    
    def _detect_gift_type(self, gift_id: int) -> str:
        """
        根据礼物ID自动识别礼物类型
        
        Args:
            gift_id: 礼物ID
            
        Returns:
            礼物类型：user/room/random
        """
        gift_id_str = str(gift_id)
        first_digit = gift_id_str[0]
        return self.gift_type_mapping.get(first_digit, "user")
    
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
    
    def _check_risk_control(
        self, skill_input: SkillInput, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        风险控制检查
        
        Args:
            skill_input: Skill 输入
            params: 参数
            
        Returns:
            检查结果
        """
        risk_config = self.metadata_config.get("risk_control", {})
        
        # 检查操作人白名单
        operator_whitelist = risk_config.get("operator_whitelist", [])
        if operator_whitelist:
            operator = skill_input.context.get("operator", "unknown")
            if operator not in operator_whitelist:
                return {
                    "allowed": False,
                    "message": f"无权限执行此操作，请联系管理员（当前操作人: {operator}）"
                }
        
        # 检查敏感参数
        sensitive_params = risk_config.get("sensitive_params", [])
        batch_count = params.get("batch_count", 1)
        if "batch_count" in sensitive_params and batch_count > 10:
            self.logger.warning(f"批量发放数量较大: {batch_count}，需要特别关注")
        
        return {"allowed": True}
    
    def _execute_gift_issue(
        self, gift_id: int, target_id: int, issue_type: str,
        duration_days: int, batch_count: int
    ) -> Dict[str, Any]:
        """
        执行礼物发放（调用 MCP 服务）
        
        Args:
            gift_id: 礼物ID
            target_id: 目标ID
            issue_type: 发放类型
            duration_days: 有效期天数
            batch_count: 批量数量
            
        Returns:
            发放结果
        """
        if not self.mcp_adapter:
            # 模拟返回（用于测试）
            return {
                "gift_id": gift_id,
                "target_id": target_id,
                "issue_type": issue_type,
                "duration_days": duration_days,
                "batch_count": batch_count,
                "success_count": batch_count,
                "failed_count": 0,
                "records": [
                    {
                        "index": i + 1,
                        "record_id": f"REC-{i+1}",
                        "status": "success"
                    }
                    for i in range(batch_count)
                ]
            }
        
        # 根据发放类型选择对应的 MCP 工具
        tool_mapping = {
            "user": "add_gift_to_user",
            "room": "add_gift_to_room",
            "random": "add_random_gift"
        }
        tool_name = tool_mapping.get(issue_type, "add_gift_to_user")
        
        # 批量发放
        results = []
        for i in range(batch_count):
            try:
                result = self.mcp_adapter.call(
                    server_name="gift-management-server",
                    tool_name=tool_name,
                    params={
                        "gift_id": gift_id,
                        "target_id": target_id,
                        "duration_days": duration_days
                    }
                )
                results.append({
                    "index": i + 1,
                    "status": "success",
                    "result": result
                })
            except Exception as e:
                results.append({
                    "index": i + 1,
                    "status": "failed",
                    "error": str(e)
                })
        
        # 统计结果
        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = batch_count - success_count
        
        return {
            "gift_id": gift_id,
            "target_id": target_id,
            "issue_type": issue_type,
            "duration_days": duration_days,
            "batch_count": batch_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "records": results
        }
    
    def _log_operation(
        self, skill_input: SkillInput, params: Dict[str, Any],
        result: Dict[str, Any]
    ):
        """
        记录操作日志
        
        Args:
            skill_input: Skill 输入
            params: 参数
            result: 执行结果
        """
        risk_config = self.metadata_config.get("risk_control", {})
        if not risk_config.get("need_log", False):
            return
        
        audit_fields = risk_config.get("audit_fields", [])
        audit_data = {
            field: params.get(field)
            for field in audit_fields
            if field in params
        }
        
        self.logger.info(
            f"操作日志 - Skill: {self.skill_name}, "
            f"操作人: {skill_input.context.get('operator', 'unknown')}, "
            f"审计数据: {audit_data}, "
            f"结果: 成功={result.get('success_count', 0)}, "
            f"失败={result.get('failed_count', 0)}"
        )
    
    def _get_error_message(self, error: str) -> str:
        """
        获取友好的错误消息
        
        Args:
            error: 原始错误信息
            
        Returns:
            友好的错误消息
        """
        error_handling = self.metadata_config.get("error_handling", {})
        
        # 匹配错误类型
        if "not found" in error.lower():
            if "gift" in error.lower():
                return error_handling.get("gift_not_found", error)
            elif "user" in error.lower() or "room" in error.lower():
                return error_handling.get("target_not_found", error)
        elif "permission" in error.lower() or "denied" in error.lower():
            return error_handling.get("permission_denied", error)
        elif "limit" in error.lower() or "exceed" in error.lower():
            return error_handling.get("batch_limit_exceeded", error)
        elif "type" in error.lower():
            return error_handling.get("invalid_gift_type", error)
        
        return error
    
    def get_param_schema(self) -> Dict[str, Any]:
        """
        获取参数 Schema
        
        Returns:
            参数 Schema 定义
        """
        # 从元数据配置中提取参数 Schema
        input_params = self.metadata_config.get("input_parameters", [])
        
        schema = {}
        for param in input_params:
            param_name = param.get("name")
            schema[param_name] = {
                "type": param.get("type"),
                "required": param.get("required", False),
                "description": param.get("description", ""),
                "default": param.get("default"),
                "enum": param.get("enum"),
                "validation": param.get("validation"),
                "alias": param.get("alias", []),
                "examples": param.get("examples", [])
            }
        
        return schema
