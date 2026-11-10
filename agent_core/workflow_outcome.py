"""Factual outcomes for supported operations; model prose is never execution evidence."""
import re
from agent_core.workflow_contracts import WRITES


def requested_effects(text):
    # This is a conservative check for documented operation phrases, not a planner.
    clauses = re.split(r"[，,。；;\n]", text)
    positive = " ".join(c for c in clauses if not re.search(r"不要|禁止|不允许|勿|不需要", c))
    required = set()
    if re.search(r"回滚", positive):
        required.add("rollback_config")
    if re.search(r"清理|清空|删除", positive):
        required.add("cleanup_data")
    if "配置" in positive and re.search(r"修改|设置|改成|更新", positive):
        required.add("update_config")
    if re.search(r"脚本|send_gifts", positive) and re.search(r"执行|运行", positive):
        required.add("run_script")
    elif re.search(r"造数|发放|发\s*\d+\s*个|发礼物|给.+发", positive):
        required.add("seed_test_data")
    return required


def verified_effect(effect, steps):
    tool, data = effect["tool"], effect["data"]
    for step in reversed(steps):
        if step["seq"] <= effect["seq"] or not step["result"].get("success"):
            continue
        result = step["result"].get("data", {})
        args = step["args"]
        if (
            tool in {"seed_test_data", "run_script", "cleanup_data"}
            and step["tool"] == "query_data"
        ):
            if args.get("table") != "gifts" and not (
                tool == "run_script" and args.get("table") == "script_runs"
            ):
                continue
            batch = data.get("batch_id")
            expected = 0 if tool == "cleanup_data" else data.get("actual")
            if (
                args.get("batch_id") == batch
                and result.get("total_quantity") is not None
            ):
                return result["total_quantity"] == expected
            # A scoped list may verify a returned batch, never an unrelated aggregate.
            matching = [r for r in result.get("rows", []) if r.get("batch_id") == batch]
            if matching:
                return sum(r.get("quantity", 0) for r in matching) == expected
        if (
            tool in {"update_config", "rollback_config"}
            and step["tool"] == "query_config"
        ):
            if (
                result.get("key") == data.get("key")
                and result.get("version") == effect["action_id"]
            ):
                return result.get("value") == data.get("after")
    return False


def finalize_outcome(state, receipts, check_request=True):
    effects = []
    for step in state["steps"]:
        if step["tool"] not in WRITES:
            continue
        aid = step["result"].get("data", {}).get("action_id")
        receipt = receipts.get(aid)
        if receipt is None:
            continue
        effects.append(
            {
                "seq": step["seq"],
                "tool": step["tool"],
                "action_id": aid,
                "status": receipt["status"],
                "data": receipt["data"],
                "actual": receipt["data"].get("actual"),
            }
        )
    observations = [
        {
            "seq": s["seq"],
            "tool": s["tool"],
            "code": s["result"].get("code"),
            "ref_id": s["result"].get("data", {}).get("ref_id"),
            "data": s["result"].get("data", {}),
        }
        for s in state["steps"]
        if s["tool"] not in WRITES
        and s["tool"] != "ask_clarification"
        and s["result"].get("success")
    ]
    verification = [
        {"action_id": e["action_id"], "verified": verified_effect(e, state["steps"])}
        for e in effects
    ]
    required = requested_effects(state["input"]) if check_request else set()
    unfulfilled = sorted(required - {e["tool"] for e in effects})
    needs_verification = check_request and bool(
        re.search(r"核验|验证|然后查询|再查询", state["input"])
    )
    verified = [v["verified"] for v in verification]
    # Explicit general verification covers all effects; a query-after-write phrase
    # only establishes that a relevant write was checked (other effects stay labelled).
    sufficient = all(verified) if re.search(r"核验|验证", state["input"]) else any(verified)
    if needs_verification and effects and not sufficient:
        unfulfilled.append("write_verification")
    message = f"已记录 {len(observations)} 次成功读取、{len(effects)} 次实际提交。"
    if not effects:
        message += "本任务没有提交写入。"
    if unfulfilled:
        message += "尚缺少所请求操作或核验的完成证据。"
    else:
        message += "结论仅覆盖以下已观察操作。"
    return {
        "message": message,
        "runtime_mode": "mock",
        "completion_scope": "observed_operations",
        "effects": effects,
        "observations": observations,
        "verification": verification,
        "unfulfilled": unfulfilled,
    }
