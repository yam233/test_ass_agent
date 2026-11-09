"""Action-level approval and safe retry on top of the existing single-step graph."""
import time

from agent_core.action_store import ActionError, scope
from agent_core.langgraph_agent.common import ensure_request_id, record_trace, start_trace
from agent_core.langgraph_agent.graph import LangGraphAgent


class GovernedAgent(LangGraphAgent):
    async def ainvoke(self, user_input, context=None):
        context = dict(context or {})
        # Caller-provided booleans can no longer approve writes in mock mode.
        context.pop("execute_confirmed", None)
        context.pop("approved", None)
        owner, session, env = scope(context)
        context.update(operator=owner, session_id=session, env=env)
        control = user_input.strip()
        controls = {"确认", "确认执行", "取消", "取消执行", "拒绝", "重试执行", "再发一次"}
        if control not in controls:
            return await super().ainvoke(user_input, context)
        request_id = ensure_request_id(context)
        started = time.time()
        try:
            if control == "再发一次":
                previous = self.mock_platforms.actions.latest(context, completed=True)
                if previous["tool"] not in {"add_gift_to_backpack", "add_gift_to_exclusive_tab", "send_gifts_to_one_room"}:
                    raise ActionError("BAD_ARGS", "最近动作不是礼物发放，请重新描述操作")
                action = self.mock_platforms.prepare(previous["tool"], previous["args"], context)
                result = self._pending_result(action)
            else:
                action_id = context.get("action_id")
                if control == "重试执行" and not action_id:
                    raise ActionError("ACTION_ID_REQUIRED", "重试需要原动作 action_id")
                action = (self.mock_platforms.actions.get(action_id, context) if action_id
                          else self.mock_platforms.actions.latest(context))
                context["action_id"] = action["action_id"]
                self.mock_platforms.check_policy(action["tool"], context)
                if control in {"取消", "取消执行", "拒绝"}:
                    self.mock_platforms.actions.deny(action["action_id"], context)
                    result = self.mock_platforms._error("APPROVAL_DENIED", "动作已取消", action["tool"], {"action_id": action["action_id"]}, "denied")
                else:
                    result = self._execute_action(action, context, approve=control in {"确认", "确认执行"})
        except ActionError as exc:
            result = self.mock_platforms._error(exc.code, str(exc), "", {"action_id": context.get("action_id")}, "blocked")
        except (ValueError, TypeError) as exc:
            result = self.mock_platforms._error("BAD_ARGS", str(exc), "")
        state = {"result": result, "context": context, "request_id": request_id, "trace": start_trace(request_id)}
        record_trace(state["trace"], "action_control", started, result.get("success", False), action_id=result.get("data", {}).get("action_id"), control=control)
        return (await self._response_node(state))["result"]

    def _execute_action(self, action, context, approve):
        action_id = action["action_id"]
        # A response may have been lost after the platform committed. Ask it first.
        receipt = self.mock_platforms.receipt(action_id, context)
        if receipt is not None:
            receipt["data"]["reconciled"] = True
            self.mock_platforms.actions.complete(action_id, receipt)
            return receipt
        if context.get("dry_run"):
            raise ActionError("BAD_ARGS", "预览请重新提交原指令，不执行已审批动作")
        try:
            if approve:
                self.mock_platforms.actions.approve(action_id, context)
            self.mock_platforms.actions.running(action_id, context)
        except ActionError:
            # Another worker may commit between our initial lookup and transition.
            receipt = self.mock_platforms.receipt(action_id, context)
            if receipt is None:
                raise
            receipt["data"]["reconciled"] = True
            self.mock_platforms.actions.complete(action_id, receipt)
            return receipt
        result = self.mock_platforms.execute(action["tool"], action["args"], context)
        self.mock_platforms.actions.complete(action_id, result)
        return result

    async def _permission_node(self, state):
        intent = state.get("intent", {})
        tool = intent.get("tool_name") or intent.get("intent")
        if tool not in self.mock_platforms.WRITE_TOOLS:
            return await super()._permission_node(state)
        started = time.time()
        context = state["context"]
        try:
            if context.get("dry_run"):
                self.mock_platforms.check_policy(tool, context)
                state["permission"] = {"allowed": True, "need_confirm": False}
            else:
                if context.get("action_id"):
                    # An existing action is executed only by explicit control commands.
                    raise ActionError("ACTION_ID_CONFLICT", "新指令不能复用 action_id；原动作请确认或重试")
                action = self.mock_platforms.prepare(tool, intent.get("params", {}), context)
                context["action_id"] = action["action_id"]
                state["permission"] = {"allowed": True, "need_confirm": True}
        except (ActionError, ValueError, TypeError) as exc:
            state["permission"] = {"allowed": False, "need_confirm": False}
            state["error"] = {"code": getattr(exc, "code", "BAD_ARGS"), "message": str(exc)}
        record_trace(state["trace"], "prepare_action", started, state["permission"]["allowed"], action_id=context.get("action_id"))
        return state

    async def _confirm_interrupt_node(self, state):
        action_id = state.get("context", {}).get("action_id")
        if not action_id:
            return await super()._confirm_interrupt_node(state)
        action = self.mock_platforms.actions.get(action_id, state["context"])
        state["result"] = self._pending_result(action)
        return state

    def _pending_result(self, action):
        if action["status"] != "pending":
            return self.mock_platforms._ok(action["tool"], {"action_id": action["action_id"], "action_status": action["status"], "snapshot": action["args"]}, status="planned")
        return self.mock_platforms._error("CONFIRM_REQUIRED", "请确认以下动作快照；变更参数需要重新提交", action["tool"],
            {"need_confirm": True, "action_id": action["action_id"], "snapshot": {
                "operator": action["operator"], "session_id": action["session_id"], "env": action["env"],
                "tool": action["tool"], "params": action["args"]}, "expires_at": action["expires_at"]}, "blocked")
