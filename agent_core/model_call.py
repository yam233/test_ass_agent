"""Bounded model attempts with durable reservations and reproducible artifacts."""
import asyncio
import os
import time
from urllib.parse import urlsplit
import httpx
from agent_core.workflow_contracts import catalog, failure
from agent_core import workflow_model


def artifact(model, output_cap, tool_catalog=None):
    config = {
        "model": getattr(model, "name", "unknown"),
        "output_cap": output_cap,
        "parallel_tool_calls": False,
        "tool_choice": "auto",
    }
    llm = getattr(model, "llm", None)
    if llm is not None:
        config["model"] = llm._setting("model")
        # Never persist credentials or query parameters from configuration.
        url = urlsplit(llm._setting("base_url") or "")
        config["endpoint"] = (
            (url.scheme + "://" + (url.hostname or "") + url.path) if url.scheme else ""
        )
    return {
        "system": workflow_model.SYSTEM,
        "tools": catalog() if tool_catalog is None else tool_catalog,
        "model_config": config,
    }


def retryable(exc):
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError)) or (
        isinstance(exc, httpx.HTTPStatusError)
        and (exc.response.status_code == 429 or 500 <= exc.response.status_code < 600)
    )


async def next_decision(runtime, state, context, messages, prompt_bound):
    try:
        configured = int(os.getenv("WORKFLOW_OUTPUT_TOKENS", "1024"))
    except ValueError:
        configured = 1024
    configured = max(1, min(configured, 2048))
    attempts = state.setdefault(
        "model_retry", {"transient": 0, "length": 0, "cap": configured}
    )
    while True:
        if runtime._timed_out(state):
            runtime._stop(state, "timeout")
            return None
        if state["model_calls"] >= state["budget"]["max_steps"]:
            runtime._stop(state, "max_steps")
            return None
        cap = min(
            attempts["cap"],
            state["budget"]["max_tokens"] - state["tokens"] - prompt_bound,
        )
        if cap < 1:
            runtime._stop(state, "budget")
            return None
        reservation = prompt_bound + cap
        state["tokens"] += reservation
        state["model_calls"] += 1
        visible = [
            t
            for t in catalog()
            if context.get("allowed_tools") is None
            or t["function"]["name"] in context["allowed_tools"]
        ]
        fingerprint = runtime.store.record_artifact(
            artifact(runtime.model, cap, visible)
        )
        state.setdefault("artifact_ids", [])
        if fingerprint not in state["artifact_ids"]:
            state["artifact_ids"].append(fingerprint)
        runtime.store.save(state)
        started = time.monotonic()
        error = None
        decision = None
        try:
            decision = await runtime.model.next(messages, context, cap)
            if not isinstance(decision, dict):
                raise ValueError("model decision must be an object")
            usage = decision.get("usage")
        except Exception as exc:
            error = exc
            usage = getattr(exc, "usage", None)
        usage = usage if isinstance(usage, dict) else {}
        used = usage.get("total_tokens")
        if type(used) is int and used >= 0:
            state["tokens"] += used - reservation
            state["reported_tokens"] += used
        else:
            state["usage_complete"] = False
        state["trace"].append(
            {
                "step": len(state["steps"]),
                "kind": "model",
                "attempt": state["model_calls"],
                "model": getattr(runtime.model, "name", "unknown"),
                "prompt_ver": fingerprint,
                "context_bytes": state.get("context_bytes", {}),
                "compaction_events": state.get("compaction_events", []),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "tokens": used,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "cost": usage.get("cost"),
                "cost_unit": "provider_reported",
                "output_cap": cap,
                "outcome": "LLM_ERROR" if error else "ok",
                "finish_reason": getattr(error, "finish_reason", None),
                "error_type": type(error).__name__ if error else None,
                "stop_reason": None,
            }
        )
        runtime.store.save(state)
        if error is None:
            state.pop("model_retry", None)
            return decision
        state["result"] = failure("LLM_ERROR", "模型请求失败：" + type(error).__name__)
        if getattr(error, "finish_reason", None) == "length" and attempts["length"] < 1:
            attempts["length"] += 1
            attempts["cap"] = min(2048, max(cap + 1, cap * 2))
            delay = 0
        elif retryable(error) and attempts["transient"] < 2:
            delay = runtime.retry_delays[
                min(attempts["transient"], len(runtime.retry_delays) - 1)
            ]
            attempts["transient"] += 1
        else:
            runtime._stop(state, "model_error")
            return None
        runtime.store.save(state)
        remaining = (
            state["budget"]["max_seconds"]
            - state["elapsed"]
            - max(0, time.time() - state["active_since"])
        )
        if delay >= remaining:
            runtime._stop(state, "timeout")
            return None
        if delay:
            await asyncio.sleep(delay)
