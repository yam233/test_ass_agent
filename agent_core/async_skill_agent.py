"""
异步 Skill Agent - LLM 全流程驱动（异步版本）

职责：
1. 异步 LLM 意图识别
2. 异步 LLM 参数提取
3. 参数适配
4. Skill 调度
5. 多操作检测和拆分

架构重构（2025-02-15）：
- 意图管理器（独立）- 意图识别、意图缓存
- 参数管理器（独立）- 参数提取、适配器链、参数验证
- SkillAgent（协调）- 协调管理器、Skill 调度

异步化改造（2025-02-16）：
- 支持异步 LLM 调用
- 提升并发处理能力 2-3x
- 降低响应时间 20-30%

可观测性增强（2025-02-16）：
- 全链路追踪
- 详细业务指标
- 性能监控

多操作支持（2025-02-18）：
- 检测并拆分多个独立操作
- 依次执行并汇总结果
"""
import time
import json
from typing import Dict, Any, Optional
import logging

from agent_core.protocol import SkillInput
from agent_core.managers.async_intent_manager import AsyncIntentManager
from agent_core.managers.async_parameter_manager import AsyncParameterManager
from agent_core.parsers.async_llm_intent_parser import AsyncLLMIntentParser
from agent_core.extractors.async_llm_param_extractor import AsyncLLMParamExtractor
from agent_core.helpers.user_prompt_helper import UserPromptHelper
from agent_core.helpers.entity_validator import EntityValidator
from agent_core.helpers.multi_operation_splitter import MultiOperationSplitter
from agent_core.helpers.batch_query_executor import BatchQueryExecutor
from agent_core.result_status import (
    STATUS_SUCCESS,
    status_from_counts,
    build_blocked_result,
)
from agent_core.layers import (
    LocalConfigLayer,
    ShortTermMemory,
    LongTermMemory,
    PerceptionLayer,
    SafetyLayer,
    ExecutionLayer,
    FormattingLayer,
)
from utils.async_llm_client import AsyncLLMClient
from utils.config_loader import ConfigLoader
from utils.monitoring import (
    trace_span,
    record_intent_recognition,
    record_param_extraction,
    record_skill_execution
)

logger = logging.getLogger(__name__)


class AsyncSkillAgent:
    """异步 Skill Agent - 协调意图管理器和参数管理器"""
    
    def __init__(self, business_code: str, skill_core):
        """
        初始化异步 Skill Agent
        
        Args:
            business_code: 业务代码
            skill_core: Skill 核心实例
        """
        self.business_code = business_code
        self.skill_core = skill_core
        self.local_config = LocalConfigLayer()
        
        # 创建异步 LLM 客户端（共享）
        self.llm_client = self._create_async_llm_client()
        
        # 创建异步意图解析器
        self.intent_parser = AsyncLLMIntentParser(self.llm_client)
        
        # 创建异步参数提取器
        self.param_extractor = AsyncLLMParamExtractor(self.llm_client)
        
        # 加载参数规则
        self.param_rules = ConfigLoader.load_business_config(
            business_code, 
            "param_rules.json"
        )
        try:
            self.business_schema = ConfigLoader.load_business_config(
                business_code,
                "business_schema.json"
            )
        except Exception:
            self.business_schema = {}
        self.framework_config = ConfigLoader.load_framework_config("agent_config.json")
        self.intent_safety_config = self.framework_config.get("intent_safety", {})
        
        # 创建意图管理器（独立）
        self.intent_manager = AsyncIntentManager(
            business_code,
            self.llm_client,
            self.intent_parser
        )
        
        # 创建参数管理器（独立）
        self.param_manager = AsyncParameterManager(
            business_code,
            self.llm_client,
            self.param_extractor,
            self.param_rules
        )
        
        # 创建实体验证器
        self.entity_validator = EntityValidator(business_code, skill_core)
        
        # 加载 Skills 注册表
        self.skills_registry = ConfigLoader.load_business_config(
            business_code,
            "skills_registry.json"
        )

        # 全局能力层
        self.perception_layer = PerceptionLayer(self.llm_client)
        self.safety_layer = SafetyLayer(self.local_config, self.framework_config)
        self.execution_layer = ExecutionLayer()
        self.formatting_layer = FormattingLayer()
        self.short_memory = ShortTermMemory(max_turns=8)
        self.long_memory = LongTermMemory()
        self.long_memory.save_skill_index(
            business_code,
            self.skills_registry.get("skills", [])
        )
        
        logger.info(f"✓ 异步 SkillAgent 初始化完成 (business: {business_code})")
    
    def _create_async_llm_client(self) -> AsyncLLMClient:
        """
        创建异步 LLM 客户端
        
        Returns:
            异步 LLM 客户端实例
        """
        # 加载 Agent 配置
        config = ConfigLoader.load_framework_config("agent_config.json")
        
        # 支持新旧两种配置格式
        if "agent_config" in config:
            # 旧格式
            agent_config = config.get("agent_config", {})
            api_key = self.local_config.get_secret("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", agent_config.get("api_key"))
            model = agent_config.get("model")
            base_url = agent_config.get("base_url")
        else:
            # 新格式
            llm_config = config.get("llm", {})
            api_key = self.local_config.get_secret("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", llm_config.get("api_key"))
            model = llm_config.get("model")
            base_url = llm_config.get("api_base")
        
        if not api_key:
            raise ValueError("API key not found in agent_config.json")
        if not model:
            raise ValueError("LLM model not found in agent_config.json")
        
        return AsyncLLMClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            enable_cache=True,
            cache_ttl=3600
        )
    
    def _get_available_skills(self) -> list:
        """
        获取可用的 Skills 列表
        
        Returns:
            Skills 列表
        """
        return self.skills_registry.get("skills", [])
    
    def _get_skill_config(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        获取 Skill 配置
        
        Args:
            skill_name: Skill 名称
            
        Returns:
            Skill 配置
        """
        for skill in self.skills_registry.get("skills", []):
            if skill.get("skill_name") == skill_name:
                return skill
        return None
    
    @trace_span("async_skill_agent_process")
    async def process(
        self, 
        user_input: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        异步处理用户请求（带追踪和指标）
        
        Args:
            user_input: 用户输入
            context: 上下文信息
            
        Returns:
            处理结果
        """
        start_time = time.time()
        
        try:
            if context is None:
                context = {}

            # 环境检查：仅支持 UAT 环境
            env = context.get("env", "uat")
            if env != "uat":
                return self._finalize_result({
                    "success": False,
                    "status": "blocked",
                    "message": f"❌ 系统仅支持 UAT 环境，当前环境: {env}。生产环境操作已被禁止。",
                    "error": "env_not_allowed",
                    "skill_name": "unknown"
                }, user_input, context)

            # 输入验证
            if not user_input or not user_input.strip():
                return self._finalize_result({
                    "success": False,
                    "status": "failed",
                    "message": UserPromptHelper.append_command_templates("❌ 用户输入不能为空"),
                    "error": "empty_input",
                    "skill_name": "unknown"
                }, user_input, context)
            
            # 限制输入长度（防止过长输入）
            if len(user_input) > 10000:
                return self._finalize_result({
                    "success": False,
                    "status": "failed",
                    "message": UserPromptHelper.append_command_templates("❌ 用户输入过长（最大10000字符）"),
                    "error": "input_too_long",
                    "skill_name": "unknown"
                }, user_input, context)
            
            # 添加业务代码到上下文
            context["business_code"] = self.business_code
            session_key = self._get_session_key(context)
            history = self.short_memory.get_history(session_key)
            if history and "history" not in context:
                context["history"] = history
            if self.business_schema:
                # 让意图识别/参数提取共享业务结构化元数据
                context["business_schema"] = self.business_schema

            if self.perception_layer.is_chat_request(user_input, self._get_available_skills()):
                chat_result = await self.perception_layer.native_chat(user_input, context)
                return self._finalize_result(chat_result, user_input, context)
            
            # 0. 多操作检测和拆分
            if MultiOperationSplitter.detect_multi_operations(user_input):
                logger.info(f"检测到多操作输入，开始拆分处理")
                result = await self._process_multi_operations(user_input, context)
                return self._finalize_result(result, user_input, context)
            
            # 1. 异步意图识别（带缓存和追踪）
            logger.info(f"开始异步意图识别: {user_input}")
            intent_start = time.time()
            intent_result = await self._recognize_intent(user_input, context)
            intent_duration = (time.time() - intent_start) * 1000
            
            logger.info(
                f"意图识别完成: skill={intent_result.skill_name}, "
                f"confidence={intent_result.confidence}"
            )
            
            # 记录意图识别指标
            record_intent_recognition(
                business_code=self.business_code,
                skill_name=intent_result.skill_name,
                confidence=intent_result.confidence,
                duration_ms=intent_duration,
                cache_hit=intent_result.cache_hit
            )
            
            # 检查置信度
            if intent_result.confidence < 0.5:
                if self.perception_layer.is_chat_request(user_input, self._get_available_skills()):
                    chat_result = await self.perception_layer.native_chat(user_input, context)
                    return self._finalize_result(chat_result, user_input, context)
                # 生成友好的用户提示
                friendly_message = UserPromptHelper.generate_low_confidence_prompt(
                    confidence=intent_result.confidence,
                    skill_name=intent_result.skill_name,
                    user_input=user_input,
                    reason=intent_result.reason
                )
                return self._finalize_result({
                    "success": False,
                    "status": "failed",
                    "message": friendly_message,
                    "error": None,  # 不显示技术性错误标签
                    "intent": intent_result.dict(),
                    "params": None,
                    "skill_name": intent_result.skill_name
                }, user_input, context)
            
            # 2. 获取 Skill 配置
            skill_config = self._get_skill_config(intent_result.skill_name)
            if not skill_config:
                return self._finalize_result({
                    "success": False,
                    "status": "failed",
                    "message": UserPromptHelper.get_unrecognized_command_reply(),
                    "data": {"intent": intent_result.dict()},
                    "skill_name": intent_result.skill_name
                }, user_input, context)

            # 执行类低置信度保护：只允许 query，不直接 execute
            execute_guard_threshold = float(
                self.intent_safety_config.get("execute_confidence_threshold", 0.80)
            )
            if (
                skill_config.get("skill_type") == "execute" and
                intent_result.confidence < execute_guard_threshold
            ):
                # 使用智能提示生成
                friendly_message = UserPromptHelper.generate_low_confidence_execute_prompt(
                    confidence=intent_result.confidence,
                    threshold=execute_guard_threshold,
                    skill_name=intent_result.skill_name,
                    user_input=user_input
                )
                return self._finalize_result({
                    "success": False,
                    "status": "blocked",
                    "message": friendly_message,
                    "error": None,
                    "intent": intent_result.dict(),
                    "params": None,
                    "skill_name": intent_result.skill_name
                }, user_input, context)
            
            # 3. 异步参数提取与适配（带追踪）
            logger.info(f"开始异步参数提取: skill={intent_result.skill_name}")
            param_start = time.time()
            param_schema = skill_config.get("param_schema", {})
            params = await self._extract_params(
                user_input,
                intent_result.skill_name,
                param_schema,
                context
            )
            param_duration = (time.time() - param_start) * 1000
            
            logger.info(f"参数提取完成: {params}")
            original_params = params.copy()
            structured_intent = self._build_structured_intent(intent_result, params, context)

            missing_params = self.execution_layer.find_missing_params(params, param_schema)
            if missing_params:
                prompt = self.execution_layer.build_missing_param_prompt(missing_params, param_schema)
                return self._finalize_result({
                    "success": False,
                    "status": "blocked",
                    "message": prompt,
                    "error": None,
                    "intent": intent_result.dict(),
                    "params": params,
                    "structured_intent": structured_intent,
                    "degraded": True,
                    "skill_name": intent_result.skill_name,
                    "data": {"missing_params": missing_params}
                }, user_input, context)
            
            # 3.5. 业务规则验证（礼物ID专属tab检查）
            if "gift_id" in params and params["gift_id"]:
                gift_id_error = UserPromptHelper.validate_gift_id_for_exclusive_tab(
                    params["gift_id"],
                    user_input
                )
                if gift_id_error:
                    return self._finalize_result({
                        "success": False,
                        "status": "blocked",
                        "message": UserPromptHelper.append_command_templates(gift_id_error),
                        "error": None,  # 不显示技术性错误标签
                        "intent": intent_result.dict(),
                        "params": params,
                        "skill_name": intent_result.skill_name
                    }, user_input, context)
            
            # 3.6. 背包礼物类型验证
            if intent_result.skill_name == "add_backpack_gift" and "gift_id" in params and params["gift_id"]:
                backpack_error = UserPromptHelper.validate_gift_id_for_backpack(
                    params["gift_id"],
                    user_input
                )
                if backpack_error:
                    return self._finalize_result({
                        "success": False,
                        "status": "blocked",
                        "message": UserPromptHelper.append_command_templates(backpack_error),
                        "error": None,  # 不显示技术性错误标签
                        "intent": intent_result.dict(),
                        "params": params,
                        "skill_name": intent_result.skill_name
                    }, user_input, context)
            
            # 4. 参数验证（规则兜底）
            validation_result = self.param_manager.validate(params, param_schema)
            
            # 记录参数提取指标
            record_param_extraction(
                business_code=self.business_code,
                skill_name=intent_result.skill_name,
                param_count=len(params),
                duration_ms=param_duration,
                validation_success=validation_result["valid"]
            )
            
            if not validation_result["valid"]:
                # 4.1 LLM 自动修正：仅对 query 场景启用，降低误执行风险
                repaired_params = None
                if intent_result.skill_type == "query":
                    repaired_params = await self._repair_params_by_llm(
                        user_input=user_input,
                        skill_name=intent_result.skill_name,
                        param_schema=param_schema,
                        params=params,
                        errors=validation_result["errors"],
                        context=context
                    )

                if repaired_params:
                    repaired_validation = self.param_manager.validate(repaired_params, param_schema)
                    if repaired_validation["valid"]:
                        logger.info("参数自动修正成功，继续执行")
                        params = repaired_validation["params"]
                        validation_result = repaired_validation
                        structured_intent["params"] = params
                    else:
                        logger.info("参数自动修正后仍不合法，降级到安全拦截")
                        params = original_params
                        validation_result = repaired_validation

                # 4.2 降级机制：仍不合法则走原有安全拦截（不执行）
                if not repaired_params or not validation_result["valid"]:
                    friendly_message = UserPromptHelper.generate_validation_error_prompt(
                        errors=validation_result["errors"],
                        params=params,
                        user_input=user_input
                    )
                    return self._finalize_result({
                        "success": False,
                        "status": "blocked",
                        "message": UserPromptHelper.append_command_templates(friendly_message),
                        "error": None,
                        "intent": intent_result.dict(),
                        "params": params,
                        "structured_intent": structured_intent,
                        "degraded": True,
                        "skill_name": intent_result.skill_name
                    }, user_input, context)
            
            # 使用验证后的参数
            params = validation_result["params"]
            structured_intent["params"] = params

            safety_decision = self.safety_layer.evaluate(skill_config, context)
            if not safety_decision.allowed:
                return self._finalize_result(build_blocked_result(
                    message=safety_decision.reason,
                    skill_name=intent_result.skill_name,
                    intent=intent_result.dict(),
                    params=params,
                    data={"status": "blocked", "policy": safety_decision.policy},
                ), user_input, context)
            if safety_decision.need_confirm:
                return self._finalize_result(build_blocked_result(
                    message=self.formatting_layer.confirmation_plan(
                        skill_config,
                        params,
                        safety_decision.reason
                    ),
                    skill_name=intent_result.skill_name,
                    intent=intent_result.dict(),
                    params=params,
                    data={
                        "pending_execute": True,
                        "pending_skill": intent_result.skill_name,
                        "params": params,
                        "status": "blocked",
                        "policy": safety_decision.policy
                    },
                ), user_input, context)

            # 4.2 查询/执行统一批量拆分（通用能力，配置驱动）
            batch_param_sets = BatchQueryExecutor.build_batch_param_sets(params, skill_config)
            if batch_param_sets:
                skill_type = skill_config.get("skill_type")
                logger.info(
                    f"检测到批量参数集: skill={intent_result.skill_name}, "
                    f"skill_type={skill_type}, items={len(batch_param_sets)}"
                )

                async def _run_batch_item(item_params: Dict[str, Any], item_index: int) -> Dict[str, Any]:
                    if intent_result.skill_name in ["execute_gift_issue", "add_user_gift", "add_room_gift", "add_backpack_gift"]:
                        if not context.get("skip_validation", False):
                            entity_valid, entity_error = self.entity_validator.validate_gift_issue_params(
                                item_params, user_input
                            )
                            if not entity_valid:
                                return {
                                    "success": False,
                                    "message": entity_error,
                                    "data": {}
                                }
                    skill_output = await self._execute_skill(
                        user_input=user_input,
                        skill_name=intent_result.skill_name,
                        params=item_params,
                        context=context
                    )
                    return {
                        "success": skill_output.success,
                        "message": skill_output.message,
                        "data": skill_output.data
                    }

                label_param = None
                batch_cfg = skill_config.get("batch_config", {})
                if batch_cfg.get("target_param"):
                    label_param = batch_cfg.get("target_param")
                elif batch_cfg.get("rules"):
                    label_param = batch_cfg["rules"][0].get("target_param")

                batch_result = await BatchQueryExecutor.run_batch_queries(
                    param_sets=batch_param_sets,
                    run_query=_run_batch_item,
                    label_param=label_param
                )
                
                # 格式化友好的批量结果消息
                batch_action = "批量查询" if skill_type == "query" else "批量执行"
                success_count = batch_result['data']['success_count']
                failed_count = batch_result['data']['failed_count']
                items = batch_result['data']['items']
                
                # 对于查询类操作，收集所有数据作为列表返回
                if skill_type == "query":
                    collected_data = []
                    for item in items:
                        if item['status'] == 'success':
                            item_data = item.get('result', {}).get('data')
                            if item_data:
                                collected_data.append(item_data)
                    
                    # 如果有收集到的数据，返回列表格式
                    if collected_data:
                        message = f"✅ {batch_action}成功！" if failed_count == 0 else f"⚠️ {batch_action}完成：成功 {success_count} 个，失败 {failed_count} 个"
                        status = status_from_counts(success_count, failed_count)
                        return self._finalize_result({
                            "success": status == STATUS_SUCCESS,
                            "status": status,
                            "message": message,
                            "data": collected_data,
                            "intent": intent_result.dict(),
                            "params": params,
                            "skill_name": intent_result.skill_name
                        }, user_input, context)
                
                # 对于执行类操作或查询失败，构建详细消息
                if failed_count == 0:
                    message_lines = [f"✅ {batch_action}成功！\n"]
                else:
                    message_lines = [f"⚠️ {batch_action}完成：成功 {success_count} 个，失败 {failed_count} 个\n"]
                
                # 添加每个项目的详细信息
                for item in items:
                    if item['status'] == 'success':
                        # 提取成功消息的关键信息
                        result_msg = item.get('result', {}).get('message', '')
                        if result_msg:
                            # 只显示消息的主要部分，去掉过多的技术细节
                            message_lines.append(result_msg.strip())
                    else:
                        # 显示失败信息
                        label = item.get('label', item.get('index'))
                        error = item.get('error', '未知错误')
                        message_lines.append(f"❌ 项目 {label}: {error}")
                
                friendly_message = "\n\n".join(message_lines)
                status = status_from_counts(success_count, failed_count)
                
                # 返回简化的数据结构
                return self._finalize_result({
                    "success": status == STATUS_SUCCESS,
                    "status": status,
                    "message": friendly_message,
                    "data": {
                        "status": status,
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "total_count": len(items)
                    },
                    "intent": intent_result.dict(),
                    "params": params,
                    "skill_name": intent_result.skill_name
                }, user_input, context)
            
            # 4.5. 实体存在性验证（针对礼物发放类操作）
            if intent_result.skill_name in ["execute_gift_issue", "add_user_gift", "add_room_gift", "add_backpack_gift"]:
                # 跳过验证的标志（避免循环调用）
                if not context.get("skip_validation", False):
                    logger.info(f"开始实体验证: skill={intent_result.skill_name}")
                    entity_valid, entity_error = self.entity_validator.validate_gift_issue_params(
                        params, user_input
                    )
                    if not entity_valid:
                        return self._finalize_result({
                            "success": False,
                            "status": "blocked",
                            "message": UserPromptHelper.append_command_templates(entity_error),
                            "error": None,  # 不显示技术性错误标签
                            "intent": intent_result.dict(),
                            "params": params,
                            "skill_name": intent_result.skill_name
                        }, user_input, context)
                    logger.info(f"✓ 实体验证通过")
            
            # 5. 调用 Skill 执行（带追踪）
            logger.info(f"开始执行 Skill: {intent_result.skill_name}")
            skill_start = time.time()
            skill_output = await self._execute_skill(
                user_input,
                intent_result.skill_name,
                params,
                context
            )
            skill_duration = (time.time() - skill_start) * 1000
            
            logger.info(
                f"Skill 执行完成: success={skill_output.success}, "
                f"message={skill_output.message}"
            )
            
            # 记录 Skill 执行指标
            record_skill_execution(
                business_code=self.business_code,
                skill_name=intent_result.skill_name,
                skill_type=intent_result.skill_type,
                success=skill_output.success,
                duration_ms=skill_duration,
                error_type=None if skill_output.success else "execution_error"
            )
            
            # 6. 返回结果
            total_duration = (time.time() - start_time) * 1000
            logger.info(f"总耗时: {total_duration:.2f}ms")
            
            return self._finalize_result({
                "success": skill_output.success,
                "status": STATUS_SUCCESS if skill_output.success else "failed",
                "message": skill_output.message,
                "data": skill_output.data,
                "intent": intent_result.dict(),
                "params": params,
                "structured_intent": structured_intent,
                "skill_name": intent_result.skill_name,
                "performance": {
                    "total_ms": total_duration,
                    "intent_ms": intent_duration,
                    "param_ms": param_duration,
                    "skill_ms": skill_duration
                }
            }, user_input, context)
            
        except Exception as e:
            logger.error(f"异步处理异常: {e}", exc_info=True)
            
            # 记录错误指标
            total_duration = (time.time() - start_time) * 1000
            record_skill_execution(
                business_code=self.business_code,
                skill_name="unknown",
                skill_type="unknown",
                success=False,
                duration_ms=total_duration,
                error_type=type(e).__name__
            )
            
            return self._finalize_result({
                "success": False,
                "status": "failed",
                "message": UserPromptHelper.append_command_templates(
                    "❌ 系统处理请求时发生异常，请稍后重试或联系管理员。"
                ),
                "error": "internal_error",
                "skill_name": "unknown"
            }, user_input if 'user_input' in locals() else "", context if 'context' in locals() else {})

    def _build_structured_intent(
        self,
        intent_result,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """构建统一结构化意图对象。"""
        return {
            "domain": self.business_code,
            "entity": intent_result.skill_name,
            "action": intent_result.skill_type,
            "filters": params or {},
            "joins": [],
            "risk_level": "medium" if intent_result.skill_type == "execute" else "low",
            "confidence": intent_result.confidence,
            "context": {
                "operator": (context or {}).get("operator"),
                "env": (context or {}).get("env"),
            }
        }

    def _get_session_key(self, context: Optional[Dict[str, Any]]) -> str:
        context = context or {}
        session_id = context.get("session_id")
        operator = context.get("operator") or "unknown"
        source = context.get("operator_source") or context.get("source") or "local"
        if session_id:
            return f"{self.business_code}:sid:{session_id}"
        return f"{self.business_code}:op:{operator}:src:{source}"

    def _finalize_result(
        self,
        result: Dict[str, Any],
        user_input: str,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        normalized = self.formatting_layer.normalize(result)
        session_key = self._get_session_key(context)
        self.short_memory.append_turn(session_key, {
            "user_input": user_input,
            "skill_name": normalized.get("skill_name"),
            "status": normalized.get("status"),
            "success": normalized.get("success"),
            "params": normalized.get("params"),
        })

        if normalized.get("skill_name") and normalized.get("skill_name") != "native_chat":
            self.long_memory.append_operation({
                "business_code": self.business_code,
                "operator": (context or {}).get("operator"),
                "env": (context or {}).get("env"),
                "skill_name": normalized.get("skill_name"),
                "status": normalized.get("status"),
                "success": normalized.get("success"),
                "params": normalized.get("params"),
            })
        return normalized

    def _execute_requires_confirmation(
        self,
        skill_config: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> bool:
        """Return whether an execute skill should stop for confirmation."""
        if hasattr(self, "safety_layer"):
            return self.safety_layer.evaluate(skill_config, context).need_confirm
        if skill_config.get("skill_type") != "execute":
            return False
        context = context or {}
        return not (context.get("execute_confirmed") or context.get("skip_execute_confirm"))

    def _build_execute_confirmation_message(
        self,
        skill_config: Dict[str, Any],
        params: Dict[str, Any],
    ) -> str:
        display_name = skill_config.get("display_name") or skill_config.get("skill_name")
        risk_level = skill_config.get("risk_level", "medium")
        param_lines = []
        for key, value in params.items():
            if value in (None, "", [], {}):
                continue
            param_lines.append(f"- {key}: {value}")
        params_text = "\n".join(param_lines) if param_lines else "- 无参数"
        return (
            f"检测到执行类操作：{display_name}\n"
            f"风险等级：{risk_level}\n\n"
            f"待执行参数：\n{params_text}\n\n"
            "为避免误操作，请回复“确认执行”继续，或回复“取消”放弃。"
        )

    async def _repair_params_by_llm(
        self,
        user_input: str,
        skill_name: str,
        param_schema: Dict[str, Any],
        params: Dict[str, Any],
        errors: Any,
        context: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """参数自动修正：让 LLM 基于校验错误修正一次。"""
        prompt = f"""你是参数修正助手。请根据校验错误修正参数，只返回 JSON 对象。

用户输入: {user_input}
技能: {skill_name}
参数Schema: {json.dumps(param_schema, ensure_ascii=False)}
当前参数: {json.dumps(params, ensure_ascii=False)}
校验错误: {json.dumps(errors, ensure_ascii=False)}
上下文: {json.dumps(context or {}, ensure_ascii=False)}

要求:
1. 只能输出 JSON，不要解释
2. 仅修正必要字段，无法修正则返回空对象 {{}}
"""
        try:
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                use_cache=False
            )
            start = response.find("{")
            end = response.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            parsed = json.loads(response[start:end])
            return parsed if isinstance(parsed, dict) and parsed else None
        except Exception as e:
            logger.warning(f"参数自动修正失败: {e}")
            return None
    
    async def _process_multi_operations(
        self,
        user_input: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        处理多操作输入
        
        Args:
            user_input: 用户输入
            context: 上下文
            
        Returns:
            汇总结果
        """
        # 拆分操作
        operations = MultiOperationSplitter.split_operations(user_input)
        
        if len(operations) <= 1:
            # 拆分失败，按单操作处理
            return await self.process(user_input, context)
        
        # 提取共享上下文
        shared_context = MultiOperationSplitter.extract_context_from_first_operation(operations)
        logger.info(f"共享上下文: {shared_context}")
        
        async def _run_operation(operation: str, index: int) -> Dict[str, Any]:
            enriched_op = MultiOperationSplitter.enrich_operation_with_context(operation, shared_context)
            logger.info(f"执行第 {index}/{len(operations)} 个操作: {enriched_op}")
            op_context = context.copy() if context else {}
            op_context["multi_operation_index"] = index
            return await self.process(enriched_op, op_context)

        summary = await BatchQueryExecutor.run_operations(operations, _run_operation)
        
        # 构建详细的结果消息
        success_count = summary['data']['success_count']
        failed_count = summary['data']['failed_count']
        
        # 汇总标题
        if failed_count == 0:
            summary_title = f"✅ 多操作执行完成：全部成功（{success_count} 个）"
        else:
            summary_title = f"⚠️ 多操作执行完成：成功 {success_count} 个，失败 {failed_count} 个"
        
        # 详细结果列表
        detail_lines = []
        for item in summary['data']['operations']:
            # 提取关键信息
            if item['status'] == 'success':
                # 显示完整的成功消息
                msg = item.get('result', {}).get('message', '')
                if msg:
                    detail_lines.append(msg.strip())
                else:
                    detail_lines.append(f"✅ 操作 {item['index']}: 成功")
            else:
                # 显示失败信息
                error = item.get('error', '未知错误')
                detail_lines.append(f"❌ 操作 {item['index']}: {error}")
        
        # 组合完整消息
        full_message = summary_title + "\n\n" + "\n".join(detail_lines)
        
        return {
            "success": failed_count == 0,  # 只有全部成功才返回 True
            "message": full_message,
            "data": {
                "success_count": success_count,
                "failed_count": failed_count,
                "total_count": len(operations)
            },  # 只返回汇总数据，不返回详细的 operations 数组
            "skill_name": "multi_operations"
        }
    
    @trace_span("intent_recognition")
    async def _recognize_intent(
        self,
        user_input: str,
        context: Dict[str, Any]
    ):
        """异步意图识别（带追踪）"""
        return await self.intent_manager.recognize(
            user_input,
            self._get_available_skills(),
            context=context
        )
    
    @trace_span("param_extraction")
    async def _extract_params(
        self,
        user_input: str,
        skill_name: str,
        param_schema: Dict[str, Any],
        context: Dict[str, Any]
    ):
        """异步参数提取（带追踪）"""
        return await self.param_manager.extract_and_adapt(
            user_input,
            skill_name,
            param_schema,
            context=context
        )
    
    @trace_span("skill_execution")
    async def _execute_skill(
        self,
        user_input: str,
        skill_name: str,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ):
        """Skill 执行（带追踪）"""
        skill_input = SkillInput(
            user_input=user_input,
            business_code=self.business_code,
            skill_name=skill_name,
            params=params,
            context=context,
            operator=context.get("operator", "ear_agent/test_user"),
            env=context.get("env", "uat")
        )
        
        return self.skill_core.execute_skill(skill_input)
    
    # clear_cache 方法已移除，避免误操作Redis缓存
