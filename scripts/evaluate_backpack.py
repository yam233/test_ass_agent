"""Deterministic state-based regression; no model calls. Run with --output report.json."""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from agent_core.langgraph_agent.llm import DeepSeekLLM
from agent_core.layers.local_config import LocalConfigLayer
from agent_core.offline_runtime import build_offline_agent

CASES_PATH = Path(__file__).resolve().parents[1] / "evals/backpack_cases.json"


def offline_agent(path):
    llm = DeepSeekLLM(LocalConfigLayer(str(Path(path).parent / "empty-settings.json")))
    llm.mode = "offline"
    return build_offline_agent(path, llm=llm)


async def run_case(case, path):
    from evals.environments.backpack import BackpackEnvironment
    environment=BackpackEnvironment(path)
    agent = environment.agent
    context = {"operator": "regression", "session_id": case["id"], "env": "uat"}
    instruction = "给用户123发10个礼物301到背包"
    scenario = case["scenario"]
    first = await agent.ainvoke("给用户123发礼物301到背包" if scenario == "missing" else instruction, context)
    action_id = first.get("data", {}).get("action_id")
    bound = {**context, **({"action_id": action_id} if action_id else {})}
    if scenario == "missing":
        result = first
    elif scenario == "denied":
        result = await agent.ainvoke("取消执行", bound)
    else:
        if scenario == "restart":
            agent = offline_agent(path)
        fault = {"auth": "f_403", "partial": "f_halfseed", "response_loss": "f_response_loss"}.get(scenario)
        result = await agent.ainvoke("确认执行", {**bound, **({"fault_id": fault} if fault else {})})
        if scenario == "response_loss":
            agent = offline_agent(path)
            result = await agent.ainvoke("重试执行", bound)
        elif scenario == "duplicate":
            result = await agent.ainvoke("确认执行", bound)
        elif scenario == "new_action":
            next_plan = await agent.ainvoke(instruction, context)
            next_id = next_plan.get("data", {}).get("action_id")
            result = await agent.ainvoke("确认执行", {**context, **({"action_id": next_id} if next_id else {})})
    # Oracle independently reads committed platform records, not the agent's claims.
    rows = agent.mock_platforms.snapshot("gifts")
    actual = sum(row["quantity"] for row in rows if row.get("user_id") == 123 and row["gift_id"] == 301)
    return {"id": case["id"], "passed": actual == case["expected_quantity"] and result.get("status") == case["expected_status"],
            "expected_quantity": case["expected_quantity"], "actual_quantity": actual,
            "expected_status": case["expected_status"], "actual_status": result.get("status"), "code": result.get("code")}


async def evaluate():
    with tempfile.TemporaryDirectory() as root:
        results = [await run_case(case, Path(root) / f"{case['id']}.sqlite") for case in json.loads(CASES_PATH.read_text())]
    return {"mode": "offline_rules", "oracle": "sqlite_platform_state", "passed": sum(r["passed"] for r in results), "total": len(results), "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    from evals.runner import evaluate as unified
    report = asyncio.run(unified(suite="backpack"))
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
