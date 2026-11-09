"""Bounded remote model acceptance on synthetic inputs. Explicit --remote required."""
import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path
from agent_core.langgraph_agent.llm import DeepSeekLLM
from agent_core.workflow_model import NativeModel
from agent_core.workflow_contracts import normalize
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget

SEED = {"table": "gifts", "user_id": 123, "gift_id": 301, "quantity": 10}
CASES = [
    ("backpack", "给用户123发10个礼物301到背包", "seed_test_data", SEED),
    ("paraphrase", "帮我给123号用户的背包加上301号礼物，数量10个。", "seed_test_data", SEED),
    ("query", "查询用户123的礼物记录", "query_data", {"table": "gifts", "user_id": 123}),
    ("scripts", "有哪些能运行的测试脚本？", "list_scripts", {}),
    ("config_read", "查询配置 gift_multiplier", "query_config", {"key": "gift_multiplier"}),
    (
        "config_write",
        "把配置 gift_multiplier 设置为2",
        "update_config",
        {"key": "gift_multiplier", "value": 2},
    ),
    ("missing_quantity", "给用户123发礼物301到背包", "ask_clarification", None),
    ("missing_user", "发10个礼物301到背包", "ask_clarification", None),
    ("ambiguous_config", "修改配置", "ask_clarification", None),
    ("cleanup_missing", "清理之前造的数据", "ask_clarification", None),
    (
        "run",
        "运行 send_gifts 脚本，用户123，礼物301，数量10个",
        "run_script",
        {"script_id": "send_gifts", "user_id": 123, "gift_id": 301, "quantity": 10},
    ),
    ("rollback_missing", "回滚配置", "ask_clarification", None),
]


def chain_passed(state, actual, index):
    if state["status"] != "completed" or actual != (10 if index == 0 else 2):
        return False
    write = "seed_test_data" if index == 0 else "update_config"
    query = "query_data" if index == 0 else "query_config"
    for pos, step in enumerate(state["steps"]):
        if step["tool"] != write or not step["result"].get("success"):
            continue
        source = step["result"].get("data", {})
        for check in state["steps"][pos + 1 :]:
            args = check["args"]
            result = check["result"]
            data = result.get("data", {})
            if check["tool"] != query or not result.get("success"):
                continue
            if (
                index == 0
                and args.get("batch_id") == source.get("batch_id")
                and args.get("batch_id")
                and data.get("total_quantity") == 10
            ):
                return True
            if (
                index == 1
                and args.get("key") == "gift_multiplier"
                and data.get("value") == 2
            ):
                return True
    return False


async def evaluate(limit=12, previous=None):
    llm = DeepSeekLLM()
    llm.mode = "remote"
    model = NativeModel(llm)
    ctx = {"operator": "acceptance", "session_id": "remote-acceptance", "env": "uat"}
    results = [
        r for r in (previous or {}).get("selection_cases", []) if r.get("passed")
    ]
    total = 0
    existing = {r["id"] for r in results}
    for name, text, tool, args in CASES[:limit]:
        if name in existing:
            continue
        started = time.monotonic()
        try:
            decision = await model.next([{"role": "user", "content": text}], ctx, 512)
            selected = decision.get("tool")
            params = decision.get("args", {})
            valid = normalize(selected, params)
            passed = selected == tool and (args is None or valid == args)
            usage = decision.get("usage")
            tokens = (usage or {}).get("total_tokens")
            if isinstance(tokens, int):
                total += tokens
            results.append(
                {
                    "id": name,
                    "passed": passed,
                    "expected_tool": tool,
                    "actual_tool": selected,
                    "params": valid,
                    "usage": usage,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                }
            )
        except Exception as exc:
            usage = getattr(exc, "usage", None)
            total += (usage or {}).get("total_tokens", 0)
            results.append(
                {
                    "id": name,
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:120],
                    "usage": usage,
                    "finish_reason": getattr(exc, "finish_reason", None),
                }
            )
            # Provider/config failure is not a reason to spend another eleven calls.
            if not isinstance(exc, (ValueError, KeyError)):
                break
        if total > 20000:
            break
    chains = []
    if results and all("error_type" not in r for r in results):
        with tempfile.TemporaryDirectory() as directory:
            for index, text in enumerate(
                ["给用户123发10个礼物301到背包，然后查询这个批次核验数量", "把配置 gift_multiplier 改成2，然后查询确认"]
            ):
                path = Path(directory) / f"chain{index}.db"
                rt = WorkflowRuntime(path, model=model)
                state = await rt.start(
                    text, ctx, Budget(max_steps=4, max_tokens=25000, max_seconds=60.0)
                )
                approvals = 0
                # Only this synthetic evaluation harness authorizes its exact fixtures.
                while state["status"] == "approval_wait" and approvals < 1:
                    pending = state["pending"]
                    expected = (
                        ("seed_test_data", SEED)
                        if index == 0
                        else ("update_config", {"key": "gift_multiplier", "value": 2})
                    )
                    if (pending["tool"], pending["args"]) != expected:
                        break
                    approvals += 1
                    state = await rt.resume(
                        state["task_id"],
                        ctx,
                        action_id=pending["action_id"],
                        decision="approve",
                    )
                actual = (
                    sum(r["quantity"] for r in rt.platform.snapshot("gifts"))
                    if index == 0
                    else rt.platform.execute(
                        "query_config", {"key": "gift_multiplier"}, ctx
                    )["data"]["value"]
                )
                passed = chain_passed(state, actual, index)
                chains.append(
                    {
                        "id": index,
                        "passed": passed,
                        "status": state["status"],
                        "actual": actual,
                        "tools": [s["tool"] for s in state["steps"]],
                        "model_calls": state["model_calls"],
                        "tokens": state["reported_tokens"],
                        "steps": state["steps"],
                    }
                )
    return {
        "mode": "remote_native_function_calls",
        "model": llm._setting("model"),
        "prompt_version": "workflow-v1",
        "selection_cases": results,
        "selection_passed": sum(r["passed"] for r in results),
        "selection_total": len(results),
        "chains": chains,
        "reported_tokens_this_run": total + sum(r["tokens"] for r in chains),
        "selection_reused": len(existing),
        "cost_usd": None,
        "cost_note": "No verified per-token tariff configured; no invented monetary estimate.",
    }


def main():
    from evals.runner import evaluate as unified

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--remote", action="store_true")
    p.add_argument("--max-total-tokens", type=int, required=True)
    p.add_argument("--output", default="evals/reports/model_acceptance_new.json")
    args = p.parse_args()
    if not args.remote:
        p.error("Supply --remote to authorize a budgeted provider run")
    report = asyncio.run(
        unified(model="remote", max_total_tokens=args.max_total_tokens, record=True)
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False
        )
    )
    return int(not report["complete"] or report["passed"] != report["total"])


if __name__ == "__main__":
    raise SystemExit(main())
