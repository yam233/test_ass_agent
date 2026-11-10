"""Small real-model acceptance against disposable mock data; explicit token cap required."""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from agent_core.layers import LocalConfigLayer
from agent_core.langgraph_agent.llm import DeepSeekLLM
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_model import NativeModel
from agent_core.workflow_store import Budget
from evals.runner import RemoteBudget


async def verify(config, token_budget):
    llm = DeepSeekLLM(LocalConfigLayer(config))
    llm.mode = "remote"
    model = RemoteBudget(NativeModel(llm), token_budget)
    ctx = {"operator": "evaluation", "session_id": "usability-acceptance", "env": "uat"}
    seed = {"table": "gifts", "user_id": 123, "gift_id": 301, "quantity": 10}
    cases = [
        ("read", "查询用户123的礼物记录", None, None, 0),
        ("seed_verify", "给用户123发10个礼物301到背包，然后查询本批次核验数量", "seed_test_data", seed, 10),
        (
            "config_verify",
            "将配置gift_multiplier改成2，然后查询核验",
            "update_config",
            {"key": "gift_multiplier", "value": 2},
            0,
        ),
        (
            "script",
            "运行脚本send_gifts，给用户123发3个礼物301",
            "run_script",
            {"script_id": "send_gifts", "user_id": 123, "gift_id": 301, "quantity": 3},
            3,
        ),
        ("cleanup", "", "cleanup_data", None, 0),
        (
            "clarify_quantity",
            "给用户123发礼物301到背包，数量稍后补充，请先问我数量",
            "seed_test_data",
            seed,
            10,
        ),
    ]
    report = {
        "model": llm._setting("model"),
        "environment": "temporary_sqlite_mock",
        "token_budget": token_budget,
        "cases": [],
    }
    failures = 0
    with tempfile.TemporaryDirectory(prefix="workflow-acceptance-") as directory:
        for name, text, tool, args, quantity in cases:
            runtime = WorkflowRuntime(
                Path(directory) / (name + ".sqlite"), model=model, retry_delays=(0, 0)
            )
            if name == "cleanup":
                from evals.models import ScriptModel

                setup = WorkflowRuntime(
                    runtime.store.db.path,
                    model=ScriptModel([{"tool": "seed_test_data", "args": seed}]),
                )
                prepared = await setup.start("seed", ctx)
                prepared = await setup.resume(
                    prepared["task_id"],
                    ctx,
                    action_id=prepared["pending"]["action_id"],
                    decision="approve",
                )
                batch = setup.platform.snapshot("gifts")[0]["batch_id"]
                args = {"batch_id": batch}
                text = "清理测试批次" + batch + "，然后查询该批次核验已清空"
            state = await runtime.start(text, ctx, Budget(max_steps=8, max_seconds=120))
            clarified = state["status"] == "clarification_wait"
            if clarified and name == "clarify_quantity":
                state = await runtime.resume(state["task_id"], ctx, reply="10")
            approved = 0
            rejected = False
            while state["status"] == "approval_wait":
                pending = state["pending"]
                if (
                    approved
                    or pending["tool"] != tool
                    or pending["args"] != args
                    or (name == "clarify_quantity" and not clarified)
                ):
                    rejected = True
                    break
                approved += 1
                state = await runtime.resume(
                    state["task_id"],
                    ctx,
                    action_id=pending["action_id"],
                    decision="approve",
                    confirm_effect="delete_batch" if tool == "cleanup_data" else None,
                    snapshot_hash=pending.get("snapshot_hash"),
                )
            actual = sum(row["quantity"] for row in runtime.platform.snapshot("gifts"))
            with runtime.platform.actions.connection() as db:
                receipts = db.execute(
                    "SELECT count(*) FROM platform_receipts"
                ).fetchone()[0]
                config_value = runtime.platform._config(db, "uat", "gift_multiplier")[
                    "value"
                ]
            expected_receipts = 2 if name == "cleanup" else int(tool is not None)
            passed = (
                not rejected
                and state["status"] == "completed"
                and actual == quantity
                and receipts == expected_receipts
                and (name != "config_verify" or config_value == 2)
                and (name != "clarify_quantity" or clarified)
            )
            report["cases"].append(
                {
                    "case_id": name,
                    "passed": passed,
                    "status": state["status"],
                    "stop_reason": state["stop_reason"],
                    "clarified": clarified,
                    "approval_guard_rejected": rejected,
                    "actual_quantity": actual,
                    "receipts": receipts,
                    "model_calls": state["model_calls"],
                    "reported_tokens": state["reported_tokens"],
                    "error_code": (state.get("result") or {}).get("code"),
                    "tools": [s["tool"] for s in state["steps"]],
                }
            )
            print(name, state["status"], "pass" if passed else "fail", flush=True)
            failures = failures + 1 if state["stop_reason"] == "model_error" else 0
            if failures >= 2 or model.remaining <= 0:
                break
    report.update(
        passed=sum(c["passed"] for c in report["cases"]),
        attempted=len(report["cases"]),
        planned=len(cases),
        charged_or_reserved_tokens=model.spent,
        remaining_tokens=model.remaining,
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--total-token-budget", type=int, required=True)
    parser.add_argument("--output", default="reports/usability-remote.json")
    args = parser.parse_args()
    if not 1 <= args.total_token_budget <= 80000:
        parser.error("token budget must be 1..80000")
    report = asyncio.run(verify(args.config, args.total_token_budget))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["passed"] == report["planned"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
