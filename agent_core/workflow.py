"""Bounded, durable single-agent function-call loop over synthetic platforms."""
import asyncio
import hashlib
import time
from agent_core.action_store import ActionError, canonical
from agent_core.workflow_contracts import SPECS, WRITES, catalog, normalize, failure
from agent_core.workflow_store import Budget
from agent_core.workflow_policy import resolve_policy, check_tool
from agent_core.model_call import next_decision
from agent_core.workflow_context import build_context
from agent_core.tool_executor import execute_tool, ISOLATED_FAULTS
from agent_core.workflow_factory import build_dependencies
from agent_core.workflow_contracts import validate_context, validate_request

from agent_core.workflow_state import TERMINAL
from agent_core.workflow_outcome import finalize_outcome
from agent_core.workflow_clarification import missing_fields, accept_reply, revise_waiting
from agent_core.workflow_decisions import CONTROLS, decision_catalog, update_task, check_intent


class WorkflowRuntime:
    def __init__(
        self,
        path=".mock_state/platforms.sqlite",
        model=None,
        retry_delays=(1, 3),
        tool_timeout=5.0,
        isolate_tools=True,
    ):
        self.platform, self.store, self.model = build_dependencies(path, model)
        self.retry_delays = retry_delays
        self.tool_timeout = max(0.01, float(tool_timeout))
        self.isolate_tools = isolate_tools

    # Retain the former private entry point for callers transitioning to contracts.
    _check_context = staticmethod(validate_context)

    async def start(self, text, context, budget=None):
        validate_request(text, context)
        state = self.store.create(text, context, budget or Budget())
        return await self.resume(state["task_id"], context)

    async def resume(
        self,
        task_id,
        context,
        action_id=None,
        decision=None,
        reply=None,
        confirm_effect=None,
        snapshot_hash=None,
    ):
        validate_context(context)
        # File locks are released by the OS even if a process is killed mid-commit.
        with self.store.lock(task_id):
            state = self.store.get(task_id, context)
            if "agent_protocol" not in state:
                state["agent_protocol"] = getattr(self.model,"agent_protocol",1)
            if state["status"] in TERMINAL:
                return state
            if self.store.cancel_requested(task_id):
                return self._cancel(state, context)
            policy = resolve_policy(context, state.get("policy"))
            context = {
                **context,
                "dry_run": state["mode"] == "dry_run",
                "allowed_tools": policy["allowed_tools"],
                "policy_version": policy["policy_version"],
            }
            state["policy"] = policy
            context.update(confirm_effect=confirm_effect, snapshot_hash=snapshot_hash)
            if state["active_since"] is not None:
                state["elapsed"] += max(0, time.time() - state["active_since"])
                state["active_since"] = None
            if revise_waiting(self.store,state,context,reply,decision):
                reply = None
            if state["status"] == "approval_wait":
                if decision is None:
                    return state
                if action_id != state["pending"]["action_id"]:
                    raise ActionError("APPROVAL_MISMATCH", "必须批准当前动作 ID")
                if decision not in {"approve", "deny"}:
                    raise ValueError("decision 必须为 approve 或 deny")
                effective = check_tool(
                    state["pending"]["tool"], context, state["policy"]
                )
                if decision == "deny":
                    self.platform.actions.deny(action_id, context)
                    return self._stop(state, "denied", "denied")
                self.platform.check_impact(
                    state["pending"]["tool"], state["pending"]["args"], effective
                )
                self.platform.actions.approve(action_id, context)
                state["status"] = "running"
                state["pending"]["phase"] = "execute"
            elif decision is not None:
                raise ActionError("APPROVAL_INVALID", "当前没有待审批动作")
            if state["status"] == "clarification_wait":
                if not reply:
                    return state
                if not isinstance(reply, str) or len(reply) > 2000:
                    raise ValueError("补充信息最长2000字")
                accept_reply(state, reply)
                if state["status"] == "clarification_wait":
                    self.store.save(state)
                    return state
            state["active_since"] = time.time()
            self.store.save(state)
            try:
                remaining = max(
                    0.000001, state["budget"]["max_seconds"] - state["elapsed"]
                )
                return await asyncio.wait_for(
                    self._drive(state, context), timeout=remaining
                )
            except asyncio.TimeoutError:
                self._settle_receipt(state, context)
                return self._stop(state, "timeout")
            except ActionError as e:
                state["result"] = failure(e.code, str(e))
                return self._stop(
                    state,
                    "budget"
                    if e.code == "CONTEXT_BUDGET"
                    else "auth"
                    if e.code in {"PERMISSION_DENIED", "APPROVAL_MISMATCH"}
                    else "bad_args"
                    if e.code == "BAD_ARGS"
                    else "unrecoverable",
                )
            finally:
                if state["active_since"] is not None:
                    state["elapsed"] += max(0, time.time() - state["active_since"])
                    state["active_since"] = None
                    self.store.save(state)

    def _receipt(self, action_id, context):
        return self.platform.actions.receipt(action_id, context)

    def _settle_receipt(self, state, context):
        pending = state.get("pending")
        if not pending or not pending.get("action_id"):
            return False
        receipt = self._receipt(pending["action_id"], context)
        if receipt is None:
            return False
        self.platform.actions.complete(pending["action_id"], receipt)
        state["result"] = self._record(state, pending["tool"], pending["args"], receipt)
        state["pending"] = None
        self.platform.actions.record_reconciliation(pending["action_id"], context)
        return True

    def _cancel(self, state, context):
        committed = self._settle_receipt(state, context)
        pending = state.get("pending")
        if pending and pending.get("action_id"):
            self.platform.actions.cancel_action(pending["action_id"], context)
        if committed:
            state["cancelled_after_commit"] = True
        return self._stop(state, "cancelled", "cancelled")

    def _stop(self, state, reason, status="failed"):
        state["status"] = status
        state["stop_reason"] = reason
        if status in TERMINAL:
            state["finished_at"] = time.time()
        if state["trace"]:
            state["trace"][-1]["stop_reason"] = reason
        self.store.save(state)
        return state

    def _messages(self, state):
        allowed = state.get("policy", {}).get("allowed_tools")
        tools = [
            t for t in catalog() if allowed is None or t["function"]["name"] in allowed
        ]
        if state.get("agent_protocol")==2:
            from agent_core.workflow_memory import SessionMemory
            if "session_memory" not in state:
                state["session_memory"] = SessionMemory(self.store.db).recent(state["scope"],state["task_id"])
            tools = decision_catalog(allowed)
        built = build_context(state, tools)
        state["context_bytes"] = built["context_bytes"]
        state["compaction_events"] = built["compaction_events"]
        return built["messages"]

    @staticmethod
    def _timed_out(state):
        active = (
            max(0, time.time() - state["active_since"])
            if state["active_since"] is not None
            else 0
        )
        return state["elapsed"] + active >= state["budget"]["max_seconds"]

    async def _drive(self, state, context):
        while state["model_calls"] <= state["budget"]["max_steps"]:
            if self.store.cancel_requested(state["task_id"]):
                return self._cancel(state, context)
            # Settling existing evidence is not another execution attempt and must
            # happen even when the crashed execution consumed the remaining budget.
            if self._settle_receipt(state, context):
                self.store.save(state)
                if state["result"]["status"] == "partial_success":
                    return self._stop(state, "partial", "partial")
            if self._timed_out(state):
                return self._stop(state, "timeout")
            if state["pending"] is not None:
                if state["pending"].get("phase") == "prepare":
                    return self._prepare_pending(state, context)
                result = await self._execute_pending(state, context)
                if result is not None:
                    return result
                continue
            if state["model_calls"] >= state["budget"]["max_steps"]:
                return self._stop(state, "max_steps")
            messages = self._messages(state)
            # UTF-8 bytes plus framing is a conservative token reservation, not a tokenizer claim.
            prompt_bound = state["context_bytes"]["total"] + 1024
            decision = await next_decision(self, state, context, messages, prompt_bound)
            if decision is None:
                return state
            if self._timed_out(state):
                return self._stop(state, "timeout")
            if state["tokens"] > state["budget"]["max_tokens"]:
                return self._stop(state, "budget")
            if "final" in decision and state.get("agent_protocol")==2:
                decision = {"tool":"finish_task", "args":{}}
            if "final" in decision:
                if not any(s["result"].get("success") for s in state["steps"]):
                    state["result"] = failure("NO_EVIDENCE", "模型未调用工具，不能声称任务已执行")
                    return self._stop(state, "no_evidence")
                state["result"] = finalize_outcome(
                    state,
                    self.platform.actions.task_receipts(state["task_id"], context),
                )
                if state["result"]["unfulfilled"]:
                    return self._stop(state, "no_evidence")
                return self._stop(state, "finished", "completed")
            tool, args = decision.get("tool"), decision.get("args")
            if not isinstance(tool, str) or not isinstance(args, dict):
                return self._stop(state, "model_error")
            try:
                if state.get("agent_protocol")==2 and tool in CONTROLS:
                    parsed = CONTROLS[tool][0](**args).model_dump()
                    if tool == "update_task":
                        result = update_task(state,parsed)
                    elif tool == "recall_memory":
                        from agent_core.workflow_memory import SessionMemory
                        result={"success":True,"code":"OK","data":{"history":SessionMemory(self.store.db).recent(state["scope"],state["task_id"],**parsed)}}
                    else:
                        from agent_core.workflow_completion import finish_task
                        state["result"] = finish_task(state,parsed,self.platform.actions.task_receipts(state["task_id"],context))
                        self._record(state,tool,parsed,{"success":not state["result"]["unfulfilled"],"code":"OK","data":{"unfulfilled":state["result"]["unfulfilled"]}})
                        if state["result"]["unfulfilled"]:
                            return self._stop(state,"no_evidence","partial" if state["result"]["effects"] else "failed")
                        return self._stop(state,"finished","completed")
                    self._record(state,tool,parsed,result)
                    self.store.save(state)
                    continue
                args = normalize(tool, args)
                if state.get("agent_protocol")==2 and tool!="ask_clarification":
                    check_intent(state,tool,args)
            except (ValueError, TypeError) as e:
                result = failure("BAD_ARGS", str(e), tool)
                state["tool_calls"] += 1
                fields = missing_fields(tool, e)
                if fields:
                    check_tool(tool, context, state["policy"])
                    result.update(
                        missing_fields=fields, question="请补充参数：" + ", ".join(fields)
                    )
                    self._record(state, tool, args, result)
                    state["clarification"] = {
                        "tool": tool,
                        "args": args,
                        "missing_fields": fields,
                    }
                    state["status"] = "clarification_wait"
                    state["result"] = result
                    self.store.save(state)
                    return state
                state["result"] = self._record(state, tool, args, result)
                state["bad_args"] += 1
                if state["bad_args"] > 1:
                    return self._stop(state, "bad_args")
                self.store.save(state)
                continue
            check_tool(tool, context, state["policy"])
            if tool == "ask_clarification":
                self._record(
                    state,
                    tool,
                    args,
                    {
                        "success": False,
                        "status": "need_more_info",
                        "code": "AMBIGUOUS",
                        "data": args,
                    },
                )
                state["status"] = "clarification_wait"
                state["result"] = args
                self.store.save(state)
                return state
            fingerprint = canonical([tool, args])
            window = state["steps"]
            if tool not in WRITES:
                # A successful write changes the observed state; rereading is verification.
                boundary = max(
                    (
                        i + 1
                        for i, s in enumerate(window)
                        if s["tool"] in WRITES and s["result"].get("success")
                    ),
                    default=0,
                )
                window = window[boundary:]
            if any(canonical([s["tool"], s["args"]]) == fingerprint for s in window):
                return self._stop(state, "loop")
            state["pending"] = {
                "tool": tool,
                "args": args,
                "attempts": 0,
                "action_id": None,
                "phase": "prepare" if tool in WRITES else "execute",
            }
            self.store.save(
                state
            )  # Persist the model decision before creating its approval.
            if tool in WRITES:
                return self._prepare_pending(state, context)
        return self._stop(state, "max_steps")

    def _prepare_pending(self, state, context):
        pending = state["pending"]
        tool, args = pending["tool"], pending["args"]
        check_tool(tool, context, state["policy"])
        if state["mode"] == "dry_run":
            policy = self.platform.check_policy(tool, context, state["policy"])
            self.platform.check_impact(tool, args, policy)
            state["result"] = {
                "success": True,
                "status": "planned",
                "code": "OK",
                "data": {
                    "tool": tool,
                    "params": args,
                    "preview": self.platform.preview(tool, args, context),
                },
            }
            state["pending"] = None
            return self._stop(state, "dry_run", "planned")
        action = self.platform.prepare(
            tool,
            args,
            {**context, "request_id": f"{state['task_id']}:{len(state['steps'])}"},
            state["policy"],
        )
        pending.update(
            action_id=action["action_id"],
            snapshot={
                "tool": tool,
                "params": args,
                "scope": state["scope"],
                "risk": SPECS[tool][1],
                "impact": self.platform.preview(tool, args, context),
            },
            expires_at=action["expires_at"],
        )
        if action.get("snapshot_hash"):
            pending["snapshot_hash"] = action["snapshot_hash"]
        state["status"] = "approval_wait"
        self.store.save(state)
        return state

    def _record(self, state, tool, args, result):
        if state.get("agent_protocol")==2:
            result = {**result,"seq":len(state["steps"])}
        compact = (
            result
            if tool == "read_ref"
            else self.store.externalize(state["task_id"], result)
        )
        state["steps"].append(
            {
                "seq": len(state["steps"]),
                "user_revision": len(state["replies"]),
                "tool": tool,
                "args": args,
                "result": compact,
                "attempts": (state.get("pending") or {}).get("attempts", 0),
            }
        )
        return compact

    async def _execute_pending(self, state, context):
        pending = state["pending"]
        tool, args = pending["tool"], pending["args"]
        ctx = {**context, "action_id": pending["action_id"]}
        receipt = self._receipt(pending["action_id"], ctx) if tool in WRITES else None
        if receipt is not None:
            self._settle_receipt(state, ctx)
            self.store.save(state)
            if receipt["status"] == "partial_success":
                return self._stop(state, "partial", "partial")
            return None
        else:
            check_tool(tool, context, state["policy"])
            if pending["attempts"] >= 3:
                return self._stop(state, "unrecoverable")
            if pending["attempts"]:
                await asyncio.sleep(self.retry_delays[min(pending["attempts"] - 1, 1)])
            if self._timed_out(state):
                return self._stop(state, "timeout")
            if tool in WRITES:
                self.platform.actions.running(pending["action_id"], ctx)
            pending["attempts"] += 1
            state["tool_calls"] += 1
            remaining = state.get("fault_remaining")
            fault = (
                state.get("fault_id") if remaining is None or remaining > 0 else None
            )
            if remaining is not None and remaining > 0:
                state["fault_remaining"] -= 1
            ctx["fault_id"] = fault
            self.store.save(state)  # Checkpoint before the side effect.
            if self._timed_out(state):
                return self._stop(state, "timeout")
            started = time.monotonic()
            execution_context = {
                **ctx,
                "fault_id": None if fault in ISOLATED_FAULTS else fault,
            }
            operation = (
                (lambda: self.store.read_ref(state["task_id"], args, context))
                if tool == "read_ref"
                else (
                    lambda: self.platform.execute(
                        tool, args, execution_context, state["policy"]
                    )
                )
            )
            if self.isolate_tools:
                remaining = (
                    state["budget"]["max_seconds"]
                    - state["elapsed"]
                    - max(0, time.time() - state["active_since"])
                )
                result = await execute_tool(
                    {
                        "path": self.store.db.path,
                        "tool": tool,
                        "args": args,
                        "context": execution_context,
                        "fault_id": fault,
                    },
                    time.monotonic() + min(self.tool_timeout, remaining),
                    operation,
                    lambda: self.store.cancel_requested(state["task_id"]),
                )
            else:
                result = operation()
            hard_timeout = result.get("hard_timeout", False)
            if tool in WRITES:
                receipt = self._receipt(pending["action_id"], ctx)
                if receipt is not None:
                    result = receipt
                    hard_timeout = False
                elif result.get("code") == "OUTCOME_UNKNOWN" and result.get(
                    "executor_exited"
                ):
                    result = failure("TRANSIENT", "本地执行者已退出且无回执，事务未提交；允许原动作重试", tool)
            if result.get("code") == "CANCELLED":
                return self._cancel(state, context)
            if hard_timeout:
                if tool in WRITES:
                    self.platform.actions.complete(
                        pending["action_id"], failure("TOOL_TIMEOUT", "工具期限已到", tool)
                    )
                state["result"] = self._record(state, tool, args, result)
                state["pending"] = None
                return self._stop(state, "tool_timeout")
            state["trace"].append(
                {
                    "step": len(state["steps"]),
                    "kind": "tool",
                    "tool": tool,
                    "args_hash": hashlib.sha256(canonical(args).encode()).hexdigest(),
                    "latency_ms": round((time.monotonic() - started) * 1000, 2),
                    "outcome": result["code"],
                    "tokens": 0,
                    "cost": 0,
                    "stop_reason": None,
                }
            )
            if tool in WRITES:
                self.platform.actions.complete(pending["action_id"], result)
                if result["code"] == "OUTCOME_UNKNOWN":
                    result = self.platform.receipt(pending["action_id"], ctx) or result
            if result["code"] in {"TRANSIENT", "TIMEOUT"} and pending["attempts"] < 3:
                self.store.save(state)
                return None
        compact = self._record(state, tool, args, result)
        state["pending"] = None
        state["result"] = compact
        self.store.save(state)
        code = result["code"]
        if self._timed_out(state):
            return self._stop(state, "timeout")
        if result["status"] == "partial_success":
            return self._stop(state, "partial", "partial")
        if result.get("success"):
            return None
        if code == "BAD_ARGS":
            state["bad_args"] += 1
            if state["bad_args"] <= 1:
                return None
            return self._stop(state, "bad_args")
        if code == "AMBIGUOUS":
            state["status"] = "clarification_wait"
            self.store.save(state)
            return state
        return self._stop(
            state, "auth" if code == "PERMISSION_DENIED" else "unrecoverable"
        )
