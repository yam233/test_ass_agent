"""Unified, offline-first evaluations. Remote runs require an explicit total budget."""
import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from agent_core.action_store import canonical
from agent_core.workflow_contracts import WRITES, normalize, catalog
from evals.environments.workflow import WorkflowEnvironment
from evals.models import ScriptModel, ChaosModel, RecordingModel, ReplayModel, signature

ROOT = Path(__file__).resolve().parents[1]
CHAIN_CASES = json.loads((ROOT / "evals/workflow_chain_cases.json").read_text())


class RemoteBudget:
    def __init__(self, model, total):
        self.model = model
        self.remaining = total
        self.spent = 0
        self.name = "remote_budgeted"
        self.llm = getattr(model, "llm", None)

    async def next(self, messages, context, max_tokens):
        from agent_core.workflow_model import SYSTEM

        reservation = (
            len(canonical([SYSTEM, catalog(), messages]).encode()) + 1024 + max_tokens
        )
        if reservation > self.remaining:
            raise ValueError("remote_budget_exhausted")
        self.remaining -= reservation
        self.spent += reservation
        result = await self.model.next(messages, context, max_tokens)
        actual = (result.get("usage") or {}).get("total_tokens")
        if type(actual) is int and actual >= 0:
            self.remaining += reservation - actual
            self.spent += actual - reservation
        return result


def baseline_key(suite, cases, mode):
    return hashlib.sha256(
        canonical(
            {
                "suite": suite,
                "cases": cases,
                "oracle": "sqlite-v2",
                "contract": catalog(),
                "metrics": "separated-v1",
                "mode": mode,
            }
        ).encode()
    ).hexdigest()


def observations_for(state):
    return [{"role": "tool", "content": canonical(s["result"])} for s in state["steps"]]


async def run_chain(case, path, model=None, record=False):
    ctx = {"operator": "evaluation", "session_id": "chains", "env": "uat"}
    scripted = ScriptModel(case["decisions"])
    selected = model or scripted
    recorder = RecordingModel(selected) if record else None
    env = WorkflowEnvironment(path, recorder or selected)
    state = await env.apply({"op": "start", "text": case["text"], "context": ctx})
    write_count = 0
    expected_writes = [d for d in case["decisions"] if d["tool"] in WRITES]
    rejected = False
    while state["status"] == "approval_wait":
        p = state["pending"]
        write_count += 1
        # Only exact synthetic case writes are approved by the evaluation harness.
        if write_count > len(expected_writes):
            rejected = True
            break
        guard = ScriptModel([expected_writes[write_count - 1]])
        expected = await guard.next(observations_for(state), ctx, 1024)
        if p["tool"] != expected["tool"] or normalize(
            p["tool"], p["args"]
        ) != normalize(expected["tool"], expected["args"]):
            rejected = True
            break
        deny = case.get("deny_write") == write_count
        state = await env.apply(
            {
                "op": "resume",
                "task_id": state["task_id"],
                "context": ctx,
                "action_id": p["action_id"],
                "decision": "deny" if deny else "approve",
                "confirm_effect": "delete_batch"
                if p["tool"] == "cleanup_data"
                else None,
                "snapshot_hash": p.get("snapshot_hash"),
            }
        )
    snapshot = env.snapshot()
    valid = (
        not rejected
        and state["status"] == case.get("status", "completed")
        and snapshot["quantity"] == case["quantity"]
        and len(snapshot["gifts"]) == case["batches"]
    )
    valid &= all(snapshot["configs"].get(k) == v for k, v in case["config"].items())
    valid &= all(r["passed"] for r in env.invariants())
    valid &= len(state["steps"]) >= 3
    if case.get("code"):
        valid &= state["result"].get("code") == case["code"]
    return {
        "case_id": case["id"],
        "passed": bool(valid),
        "status": state["status"],
        "steps": len(state["steps"]),
        "actual_quantity": snapshot["quantity"],
        "write_attempts": sum(
            1 for t in state["trace"] if t["kind"] == "tool" and t["tool"] in WRITES
        ),
        "committed_actions": len(snapshot["receipts"]),
        "approved_actions": write_count - int(rejected),
        "reported_tokens": state["reported_tokens"],
        "records": recorder.records if recorder else None,
    }


async def run_chaos(kind, path, seed):
    ctx = {
        "operator": "evaluation",
        "session_id": "chaos",
        "env": "prod" if kind == "unauthorized" else "uat",
    }
    env = WorkflowEnvironment(path, ChaosModel(seed, kind))
    action = {"op": "start", "text": kind, "context": ctx}
    if kind == "budget":
        action["budget"] = {"max_steps": 1}
    state = await env.apply(action)
    if state["status"] == "approval_wait":
        p = state["pending"]
        if kind == "repeat_write":
            state = await env.apply(
                {
                    "op": "resume",
                    "task_id": state["task_id"],
                    "context": ctx,
                    "action_id": p["action_id"],
                    "decision": "approve",
                }
            )
    expected = {
        "normal": "finished",
        "repeat_write": "loop",
        "repeat_read": "loop",
        "wrong_tool": "bad_args",
        "missing_args": None,
        "unauthorized": "auth",
        "budget": "max_steps",
    }
    snap = env.snapshot()
    limit = 10 if kind == "repeat_write" else 0
    contained = state["stop_reason"] == expected[kind] and snap["quantity"] == limit
    if kind == "missing_args":
        contained &= state["status"] == "clarification_wait" and bool(
            state["result"].get("missing_fields")
        )
    return {
        "case_id": "chaos_" + kind,
        "passed": contained,
        "normal": kind == "normal",
        "unsafe_escape": snap["quantity"] > limit
        or len(snap["receipts"]) > (1 if kind == "repeat_write" else 0)
        or bool(snap["configs"]),
        "status": state["status"],
        "stop_reason": state["stop_reason"],
        "steps": len(state["steps"]),
        "actual_quantity": snap["quantity"],
    }


async def evaluate(
    suite="workflow",
    model="fixture",
    repeat=1,
    seed=0,
    baseline=None,
    max_total_tokens=None,
    replay=None,
    record=False,
):
    if suite not in {"workflow", "backpack"}:
        raise ValueError("unknown suite")
    if model not in {"fixture", "chaos", "replay", "remote"}:
        raise ValueError("unknown model mode")
    if not 1 <= repeat <= 10:
        raise ValueError("repeat must be 1..10")
    if model == "remote" and (
        type(max_total_tokens) is not int or max_total_tokens <= 0
    ):
        raise ValueError("remote requires explicit total token budget / 预算")
    if suite == "backpack" and model != "fixture":
        raise ValueError("backpack supports offline fixture only")
    if model == "replay" and replay is None:
        raise ValueError("replay requires recorded trajectories")
    mode = {
        "fixture": "runtime_fixture",
        "chaos": "runtime_chaos",
        "replay": "historical_replay",
        "remote": "live_model",
    }[model]
    from scripts.evaluate_workflow import (
        CASES as BASE_CASES,
        run_case as legacy_workflow,
    )
    from scripts.evaluate_backpack import CASES_PATH, run_case as legacy_backpack

    cases = (
        json.loads(CASES_PATH.read_text())
        if suite == "backpack"
        else BASE_CASES + CHAIN_CASES
    )
    if model == "chaos":
        cases = [
            "normal",
            "wrong_tool",
            "missing_args",
            "repeat_read",
            "repeat_write",
            "unauthorized",
            "budget",
        ]
    if model == "replay":
        cases = CHAIN_CASES
    remote = None
    if model == "remote":
        from agent_core.langgraph_agent.llm import DeepSeekLLM
        from agent_core.workflow_model import NativeModel
        from scripts.evaluate_model import CASES as SELECTION

        llm = DeepSeekLLM()
        llm.mode = "remote"
        remote = RemoteBudget(NativeModel(llm), max_total_tokens)
        cases = [
            {"id": c[0], "text": c[1], "tool": c[2], "args": c[3]} for c in SELECTION
        ] + CHAIN_CASES[:6]
    key = baseline_key(suite, cases, mode)
    if baseline and baseline.get("baseline_key") != key:
        raise ValueError("baseline / 基线用例、环境、判分口径不匹配")
    rows = []
    with tempfile.TemporaryDirectory() as directory:
        for trial in range(repeat):
            for index, case in enumerate(cases):
                path = Path(directory) / f"{trial}-{index}.sqlite"
                if model == "chaos":
                    row = await run_chaos(case, path, seed + trial * 100 + index)
                elif suite == "backpack":
                    row = await legacy_backpack(case, path)
                    row["case_id"] = row["id"]
                elif model == "fixture" and index < len(BASE_CASES):
                    row = await legacy_workflow(case, path)
                elif model == "remote" and "tool" in case:
                    try:
                        result = await remote.next(
                            [{"role": "user", "content": case["text"]}],
                            {"operator": "acceptance", "env": "uat"},
                            1024,
                        )
                        args = normalize(result["tool"], result["args"])
                        passed = result["tool"] == case["tool"] and (
                            case["args"] is None or args == case["args"]
                        )
                        row = {
                            "case_id": case["id"],
                            "passed": passed,
                            "selection": True,
                            "decision": result,
                        }
                    except Exception as exc:
                        row = {
                            "case_id": case["id"],
                            "passed": False,
                            "selection": True,
                            "error_type": type(exc).__name__,
                        }
                else:
                    replay_model = (
                        ReplayModel(replay.get(f"{case['id']}:{trial}", []))
                        if model == "replay"
                        else None
                    )
                    row = await run_chain(
                        case,
                        path,
                        remote or replay_model,
                        record=record or model == "remote",
                    )
                rows.append({**row, "trial": trial + 1})
                if remote and remote.remaining <= 0:
                    break
    passed = sum(bool(r["passed"]) for r in rows)
    n = len(rows)
    selections = [r for r in rows if r.get("selection")]
    groups = {}
    for row in rows:
        groups.setdefault(row["case_id"], []).append(bool(row["passed"]))
    metrics = {
        "all_runs_pass_rate": sum(len(v) == repeat and all(v) for v in groups.values())
        / len(cases)
        if cases
        else None,
        "runtime_pass_rate": passed / n if n else None,
        "decision_accuracy": sum(r["passed"] for r in selections) / len(selections)
        if selections
        else None,
    }
    if model == "chaos":
        bad = [r for r in rows if not r["normal"]]
        normal = [r for r in rows if r["normal"]]
        metrics.update(
            runtime_containment=sum(r["passed"] for r in bad) / len(bad),
            unsafe_escape_rate=sum(r["unsafe_escape"] for r in bad) / len(bad),
            normal_false_rejection_rate=sum(not r["passed"] for r in normal)
            / len(normal),
        )
    result = {
        "suite": suite,
        "mode": mode,
        "baseline_key": key,
        "case_count": len(cases),
        "repeat": repeat,
        "seed": seed,
        "passed": passed,
        "total": n,
        "expected_total": len(cases) * repeat,
        "complete": n == len(cases) * repeat,
        "metrics": metrics,
        "cases": rows,
        "cost_usd": None if remote else 0,
        "charged_or_reserved_tokens": remote.spent if remote else 0,
        "prompt_contract_hash": signature(),
        "notes": [
            "Replay checks historical decisions, not the current model.",
            "Fixture routing is not LLM decision accuracy.",
            "Every repeated trial is executed; no reuse of successful trials.",
        ],
    }
    if baseline:
        result["comparison"] = {"before": baseline["metrics"], "after": metrics}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--suite", choices=["workflow", "backpack"], default="workflow")
    p.add_argument(
        "--model", choices=["fixture", "chaos", "replay", "remote"], default="fixture"
    )
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-total-tokens", type=int)
    p.add_argument("--baseline")
    p.add_argument("--replay")
    p.add_argument("--record", action="store_true")
    p.add_argument("--output", default="evals/reports/unified.json")
    args = p.parse_args()
    previous = json.loads(Path(args.baseline).read_text()) if args.baseline else None
    trajectories = json.loads(Path(args.replay).read_text()) if args.replay else None
    try:
        report = asyncio.run(
            evaluate(
                args.suite,
                args.model,
                args.repeat,
                args.seed,
                previous,
                args.max_total_tokens,
                trajectories,
                args.record,
            )
        )
    except ValueError as exc:
        p.error(str(exc))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    path.with_suffix(".jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in report["cases"])
    )
    records = {
        f"{r['case_id']}:{r['trial']-1}": r["records"]
        for r in report["cases"]
        if r.get("records")
    }
    if records:
        path.with_suffix(".trajectories.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n"
        )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False
        )
    )
    return int(not report["complete"] or report["passed"] != report["total"])


if __name__ == "__main__":
    raise SystemExit(main())
