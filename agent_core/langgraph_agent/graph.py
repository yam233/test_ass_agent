"""LangGraph orchestration for the test assistant."""
import logging
import time
from typing import Any, Dict, Optional, TypedDict

from agent_core.langgraph_agent.common import (
    ErrorCode,
    IntentPayload,
    attach_trace,
    ensure_request_id,
    error_result,
    format_result,
    record_trace,
    start_trace,
    validate_payload,
)
from agent_core.langgraph_agent.compat import build_branching_state_graph
from agent_core.langgraph_agent.llm import DeepSeekLLM
from agent_core.langgraph_agent.memory import ShortTermMemory, SkillVectorIndex
from agent_core.langgraph_agent.metadata import PlatformMetadataRegistry, default_metadata_registry
from agent_core.langgraph_agent.permissions import PermissionGuard
from agent_core.langgraph_agent.tools import default_tools

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    user_input: str
    context: Dict[str, Any]
    intent: Dict[str, Any]
    permission: Dict[str, Any]
    missing_params: list[str]
    error: Dict[str, Any]
    result: Dict[str, Any]
    trace: Dict[str, Any]
    request_id: str


class LangGraphAgent:
    """Business/chat router with permission, tool, memory, and fallback graph."""

    def __init__(
        self,
        tools: Optional[Dict[str, Any]] = None,
        llm: Optional[DeepSeekLLM] = None,
        memory: Optional[ShortTermMemory] = None,
        skill_index: Optional[SkillVectorIndex] = None,
        metadata_registry: Optional[PlatformMetadataRegistry] = None,
    ):
        self.llm = llm or DeepSeekLLM()
        self.metadata_registry = metadata_registry or default_metadata_registry()
        self.tools = tools or default_tools(registry=self.metadata_registry)
        self.memory = memory or ShortTermMemory(turns=6)
        self.skill_index = skill_index or SkillVectorIndex()
        self.guard = PermissionGuard()
        self._graph = build_branching_state_graph(
            AgentState,
            {
                "parse": self._parse_node,
                "chat_response": self._chat_response_node,
                "param_check": self._param_check_node,
                "clarify": self._clarify_node,
                "permission_check": self._permission_node,
                "confirm_interrupt": self._confirm_interrupt_node,
                "tool_execute": self._tool_execute_node,
                "error_handler": self._error_handler_node,
                "memory": self._memory_node,
                "response": self._response_node,
            },
            {
                "chat_response": "memory",
                "clarify": "memory",
                "confirm_interrupt": "memory",
                "tool_execute": "memory",
                "error_handler": "memory",
                "memory": "response",
                "response": "END",
            },
            {
                "parse": (self._route_after_parse, {
                    "chat": "chat_response",
                    "param_check": "param_check",
                    "error": "error_handler",
                }),
                "param_check": (self._route_after_param_check, {
                    "clarify": "clarify",
                    "permission": "permission_check",
                }),
                "permission_check": (self._route_after_permission, {
                    "confirm": "confirm_interrupt",
                    "tool": "tool_execute",
                    "error": "error_handler",
                }),
            },
        )

    async def ainvoke(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        request_context = dict(context or {})
        request_id = ensure_request_id(request_context)
        state: AgentState = {
            "user_input": user_input,
            "context": request_context,
            "request_id": request_id,
            "trace": start_trace(request_id),
        }
        try:
            if self._graph is not None:
                final_state = await self._graph.ainvoke(state)
                return final_state.get("result", {})
            final_state = await self._run_fallback(state)
            return final_state.get("result", {})
        except Exception as exc:
            logger.exception("langgraph_agent_unhandled_error request_id=%s", request_id)
            state["error"] = {
                "code": ErrorCode.SYSTEM_ERROR.value,
                "message": f"系统异常: {type(exc).__name__}",
            }
            state = await self._error_handler_node(state)
            state = await self._memory_node(state)
            state = await self._response_node(state)
            return state.get("result", {})

    async def _run_fallback(self, state: AgentState) -> AgentState:
        state = await self._parse_node(state)
        route = self._route_after_parse(state)
        if route == "chat":
            state = await self._chat_response_node(state)
        elif route == "error":
            state = await self._error_handler_node(state)
        else:
            state = await self._param_check_node(state)
            if self._route_after_param_check(state) == "clarify":
                state = await self._clarify_node(state)
            else:
                state = await self._permission_node(state)
                permission_route = self._route_after_permission(state)
                if permission_route == "confirm":
                    state = await self._confirm_interrupt_node(state)
                elif permission_route == "error":
                    state = await self._error_handler_node(state)
                else:
                    state = await self._tool_execute_node(state)
        state = await self._memory_node(state)
        state = await self._response_node(state)
        return state

    async def _parse_node(self, state: AgentState) -> AgentState:
        started = time.time()
        try:
            context = state.get("context", {})
            raw_intent = self._resume_pending_intent(state)
            if raw_intent is None:
                raw_intent = await self.llm.classify_intent(state.get("user_input", ""), context)
            ok, payload, reason = validate_payload(IntentPayload, raw_intent)
            if not ok:
                payload = {"intent": "unclear", "tool_name": "", "params": {}, "is_chat": False, "error": reason}
            if not payload.get("is_chat"):
                payload["tool_name"] = self.metadata_registry.resolve_tool_name(payload)
            state["intent"] = payload
            record_trace(state["trace"], "parse", started, True, intent=payload.get("intent"))
            logger.info("agent_node=parse request_id=%s intent=%s", state.get("request_id"), payload.get("intent"))
        except Exception as exc:
            state["error"] = {"code": ErrorCode.LLM_ERROR.value, "message": f"意图解析失败: {type(exc).__name__}"}
            record_trace(state["trace"], "parse", started, False, error=type(exc).__name__)
        return state

    async def _chat_response_node(self, state: AgentState) -> AgentState:
        started = time.time()
        try:
            if isinstance(self.llm, DeepSeekLLM):
                reply = await self.llm.chat(state.get("user_input", ""), context=state.get("context", {}))
            else:
                reply = await self.llm.chat(state.get("user_input", ""))
            state["result"] = {
                "success": True,
                "status": "success",
                "code": ErrorCode.OK.value,
                "message": reply,
                "data": {},
                "tool_name": "native_chat",
            }
            record_trace(state["trace"], "chat_response", started, True)
        except Exception as exc:
            state["error"] = {"code": ErrorCode.LLM_ERROR.value, "message": f"闲聊回复失败: {type(exc).__name__}"}
            record_trace(state["trace"], "chat_response", started, False, error=type(exc).__name__)
        return state

    async def _param_check_node(self, state: AgentState) -> AgentState:
        started = time.time()
        intent = state.get("intent", {})
        missing = self._missing_params(intent)
        state["missing_params"] = missing
        if missing:
            self.memory.set_pending(state.get("context", {}), {"intent": intent, "missing_params": missing})
        else:
            self.memory.clear_pending(state.get("context", {}))
        record_trace(state["trace"], "param_check", started, True, missing_params=missing)
        return state

    async def _clarify_node(self, state: AgentState) -> AgentState:
        started = time.time()
        missing = state.get("missing_params", [])
        state["result"] = error_result(
            ErrorCode.NEED_MORE_INFO,
            f"还缺少必要参数: {', '.join(missing)}。请补充后我再继续。",
            {"missing_params": missing, "pending_intent": state.get("intent", {})},
            status="need_more_info",
            request_id=state.get("request_id"),
        )
        record_trace(state["trace"], "clarify", started, True, missing_params=missing)
        return state

    async def _permission_node(self, state: AgentState) -> AgentState:
        started = time.time()
        intent = state.get("intent", {})
        action = self._permission_action(intent)
        context = {**state.get("context", {}), "tool_name": intent.get("tool_name") or intent.get("intent")}
        decision = self.guard.evaluate(action, context)
        state["permission"] = {
            "allowed": decision.allowed,
            "need_confirm": decision.need_confirm,
            "message": decision.message,
            "code": decision.code,
            "action": action,
        }
        if not decision.allowed:
            state["error"] = {
                "code": decision.code or ErrorCode.PERMISSION_DENIED.value,
                "message": decision.message or "权限校验失败",
            }
        record_trace(
            state["trace"],
            "permission",
            started,
            decision.allowed,
            action=action,
            need_confirm=decision.need_confirm,
            code=decision.code,
        )
        return state

    async def _confirm_interrupt_node(self, state: AgentState) -> AgentState:
        started = time.time()
        permission = state.get("permission", {})
        state["result"] = error_result(
            permission.get("code") or ErrorCode.CONFIRM_REQUIRED,
            permission.get("message", "该操作需要管理员二次确认"),
            {"need_confirm": True, "pending_intent": state.get("intent", {})},
            status="blocked",
            request_id=state.get("request_id"),
        )
        self.memory.set_pending(state.get("context", {}), {"intent": state.get("intent", {}), "confirm_required": True})
        record_trace(state["trace"], "confirm_interrupt", started, True)
        return state

    async def _tool_execute_node(self, state: AgentState) -> AgentState:
        started = time.time()
        intent = state.get("intent", {})
        tool_name = intent.get("tool_name") or intent.get("intent")
        tool = self.tools.get(tool_name)
        if not tool:
            state["result"] = error_result(
                ErrorCode.TOOL_NOT_FOUND,
                "我还没识别到可执行的测试能力，请补充目标对象或操作类型。",
                {"intent": intent},
                status="need_more_info",
                request_id=state.get("request_id"),
                tool_name=tool_name,
            )
            record_trace(state["trace"], "tool_execute", started, False, tool_name=tool_name, code=ErrorCode.TOOL_NOT_FOUND.value)
            return state

        try:
            params = dict(intent.get("params") or {})
            params["context"] = state.get("context", {})
            result = tool.invoke(params) if hasattr(tool, "invoke") else tool._run(**params)
            state["result"] = format_result(result, tool_name)
            tool_meta = self.metadata_registry.get_tool(tool_name)
            if tool_meta:
                state["result"].setdefault("data", {})
                if isinstance(state["result"]["data"], dict):
                    state["result"]["data"].setdefault("skill_name", intent.get("intent"))
                    state["result"]["data"].setdefault("tool_name", tool_name)
                    state["result"]["data"].setdefault("platform", tool_meta.platform)
                    state["result"]["data"].setdefault("executor", tool_meta.executor)
                    state["result"]["data"].setdefault("service", tool_meta.service)
            record_trace(
                state["trace"],
                "tool_execute",
                started,
                state["result"].get("success", False),
                tool_name=tool_name,
                platform=(self.metadata_registry.get_tool(tool_name).platform if self.metadata_registry.get_tool(tool_name) else None),
            )
        except Exception as exc:
            state["error"] = {
                "code": ErrorCode.TOOL_EXECUTION_ERROR.value,
                "message": f"工具执行失败: {type(exc).__name__}",
                "tool_name": tool_name,
            }
            record_trace(state["trace"], "tool_execute", started, False, tool_name=tool_name, error=type(exc).__name__)
            state = await self._error_handler_node(state)
        return state

    async def _error_handler_node(self, state: AgentState) -> AgentState:
        started = time.time()
        error = state.get("error", {})
        state["result"] = error_result(
            error.get("code") or ErrorCode.SYSTEM_ERROR,
            error.get("message") or "系统处理失败",
            {"error": error},
            status="failed",
            request_id=state.get("request_id"),
            tool_name=error.get("tool_name", ""),
        )
        record_trace(state["trace"], "error_handler", started, True, code=state["result"].get("code"))
        return state

    async def _memory_node(self, state: AgentState) -> AgentState:
        started = time.time()
        self.memory.add_turn(state.get("user_input", ""), state.get("result", {}), state.get("context", {}))
        result = state.get("result", {})
        intent = state.get("intent", {})
        if result.get("success") and intent and not intent.get("is_chat"):
            self.skill_index.upsert([{
                "operator": state.get("context", {}).get("operator"),
                "skill_name": intent.get("intent"),
                "tool_name": result.get("tool_name") or intent.get("tool_name"),
                "platform": (
                    self.metadata_registry.get_tool(intent.get("tool_name", "")).platform
                    if self.metadata_registry.get_tool(intent.get("tool_name", ""))
                    else None
                ),
                "user_input": state.get("user_input", ""),
                "params": intent.get("params", {}),
            }])
        record_trace(state["trace"], "memory", started, True)
        return state

    async def _response_node(self, state: AgentState) -> AgentState:
        started = time.time()
        result = format_result(state.get("result", {}))
        record_trace(state["trace"], "response", started, True)
        state["result"] = attach_trace(result, state.get("trace", {}), state.get("request_id", ""))
        state["result"]["data"]["llm_mode"] = getattr(self.llm, "mode", "custom")
        state["result"]["data"]["runtime_mode"] = getattr(self, "runtime_mode", "legacy")
        return state

    def _route_after_parse(self, state: AgentState) -> str:
        if state.get("error"):
            return "error"
        if state.get("intent", {}).get("is_chat"):
            return "chat"
        return "param_check"

    def _route_after_param_check(self, state: AgentState) -> str:
        return "clarify" if state.get("missing_params") else "permission"

    def _route_after_permission(self, state: AgentState) -> str:
        permission = state.get("permission", {})
        if not permission.get("allowed", False):
            return "error"
        if permission.get("need_confirm"):
            return "confirm"
        return "tool"

    def _resume_pending_intent(self, state: AgentState) -> Optional[Dict[str, Any]]:
        context = state.get("context", {})
        pending = self.memory.get_pending(context)
        if not pending:
            return None
        if pending.get("confirm_required"):
            if state.get("user_input", "").strip() not in {"确认", "确认执行"}:
                self.memory.clear_pending(context)
                return None
            context["execute_confirmed"] = True
        intent = dict(pending.get("intent") or {})
        params = dict(intent.get("params") or {})
        user_input = state.get("user_input", "")
        if "script_path" in pending.get("missing_params", []) and not params.get("script_path"):
            params["script_path"] = DeepSeekLLM._extract_script_path(user_input)
        if "keyword" in pending.get("missing_params", []) and not params.get("keyword"):
            params["keyword"] = user_input.strip()
        for field in pending.get("missing_params", []):
            if field not in params or params.get(field) in (None, ""):
                extracted = DeepSeekLLM.extract_named_value(user_input, field)
                if extracted not in (None, ""):
                    params[field] = extracted
        intent["params"] = params
        return intent

    def _missing_params(self, intent: Dict[str, Any]) -> list[str]:
        tool_name = intent.get("tool_name") or intent.get("intent")
        params = intent.get("params") or {}
        tool_meta = self.metadata_registry.get_tool(tool_name)
        if tool_meta:
            return tool_meta.missing_params(params)
        required = {
            "script_read": ["script_path"],
            "script_run": ["script_path"],
            "db_query": ["sql"],
        }.get(tool_name, [])
        if tool_name == "db_query" and params.get("dialect") == "mongo":
            required = ["query"]
        return [name for name in required if params.get(name) in (None, "", [], {})]

    def _permission_action(self, intent: Dict[str, Any]) -> str:
        if intent.get("is_chat"):
            return "chat"
        tool_name = intent.get("tool_name") or intent.get("intent")
        tool_meta = self.metadata_registry.get_tool(tool_name)
        if tool_meta:
            if tool_meta.platform == "test_script":
                return "script_execute"
            skill = self.metadata_registry.get_skill(intent.get("intent", ""))
            if skill and skill.skill_type == "execute":
                return "execute"
            return "query"
        return {
            "db_query": "query",
            "db_export": "export",
            "db_write": "write",
            "backend_feature": "metadata",
            "script_scan": "script_scan",
            "script_read": "script_read",
            "script_run": "script_execute",
        }.get(tool_name, "metadata")
