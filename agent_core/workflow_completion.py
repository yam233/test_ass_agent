"""Check model-proposed goal assessments against observed facts, never model prose."""
import re
from agent_core.action_store import canonical
from agent_core.workflow_contracts import WRITES, normalize
from agent_core.workflow_outcome import finalize_outcome, verified_effect


def matches(expected, actual):
    return all(
        k in actual and canonical(actual[k]) == canonical(v)
        for k, v in expected.items()
    )


def write_evidence(goal, steps, receipts):
    expected = normalize(goal["tool"], goal["args"])
    for step in steps:
        if step["tool"] != goal["tool"] or not matches(expected, step["args"]):
            continue
        aid = step["result"].get("data", {}).get("action_id")
        receipt = receipts.get(aid)
        if receipt and receipt.get("success") and receipt.get("status") == "success":
            data = receipt.get("data", {})
            if "expected" in data and data.get("actual") != data["expected"]:
                continue
            return {
                "seq": step["seq"],
                "tool": step["tool"],
                "action_id": aid,
                "status": receipt["status"],
                "data": data,
            }
    return None


def read_is_current(step, all_steps):
    """Never let the model cherry-pick an older observation over newer state."""
    for later in all_steps:
        if later["seq"] <= step["seq"] or not later["result"].get("success"):
            continue
        if step["tool"] == "query_config":
            if (
                later["tool"] in {"query_config", "update_config", "rollback_config"}
                and (
                    later["args"].get("key")
                    or later["result"].get("data", {}).get("key")
                )
                == step["args"]["key"]
            ):
                return False
        elif step["tool"] == "query_data":
            if later["tool"] in {"seed_test_data", "run_script", "cleanup_data"}:
                return False
            if later["tool"] == "query_data" and later["args"].get("table") == step[
                "args"
            ].get("table"):
                a, b = step["args"], later["args"]
                if not any(
                    a.get(k) is not None and b.get(k) is not None and a[k] != b[k]
                    for k in ("batch_id", "user_id")
                ):
                    return False
    return True


def ensure_read(goal, steps, all_steps):
    args = normalize("update_config", goal["args"])
    matching = [
        s
        for s in steps
        if s["tool"] == "query_config"
        and s["args"].get("key") == args["key"]
        and matches(
            {"key": args["key"], "value": args["value"]}, s["result"].get("data", {})
        )
    ]
    for step in reversed(matching):
        if read_is_current(step, all_steps):
            return step
    return None


def fact_sentence(goal, assessment, evidence):
    status = assessment["status"]
    args = goal["args"]
    kind = goal["kind"]
    if status == "unsupported":
        return f"目标{goal['id']}超出当前工具能力，未执行。"
    if status == "unfulfilled":
        return f"目标{goal['id']}尚未完成。"
    if kind == "ensure_config":
        suffix = "无需修改。" if status == "not_needed" else "已查询确认目标值。"
        return f"配置{args['key']}当前为{canonical(args['value'])}，{suffix}"
    if kind == "verify":
        return f"目标{goal['write_goal_id']}已通过对应操作后的查询核验。"
    step = evidence[-1]
    data = step["result"].get("data", {})
    if kind == "write":
        if goal["tool"] in {"seed_test_data", "run_script"}:
            return f"已为用户{args['user_id']}提交礼物{args['gift_id']}，实际数量{data['actual']}，批次{data['batch_id']}。"
        if goal["tool"] == "cleanup_data":
            return f"已清理批次{args['batch_id']}，实际清理数量{data.get('actual',0)}。"
        return f"配置{data.get('key','')}已变更为{canonical(data.get('after'))}，回执{data.get('action_id','')}。"
    if goal["tool"] == "query_config":
        return f"查询到配置{data.get('key')}为{canonical(data.get('value'))}。"
    if goal["tool"] == "query_data":
        return f"查询到{data.get('row_count',0)}条记录，礼物合计{data.get('total_quantity',0)}个。"
    if goal["tool"] == "list_scripts":
        return "已查询内置脚本列表，详见查询结果。"
    return "已读取结果引用，详见查询结果。"


def render_answer(template, facts):
    ids = re.findall(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}", template)
    remainder = re.sub(r"\{\{[a-zA-Z][a-zA-Z0-9_]*\}\}", "", template)
    # Model chooses composition. Free claims cannot be proven and fall back to facts.
    valid = sorted(ids) == sorted(facts) and not re.sub(
        r"[\s，。；：、！？,.!?:;\-•]", "", remainder
    )
    answer = template
    if valid:
        for key, value in facts.items():
            answer = answer.replace("{{" + key + "}}", value)
    else:
        answer = "\n".join(facts.values())
    return "【mock 环境】" + answer, not valid


def finish_task(state, args, receipts):
    understanding = state.get("understanding")
    if not understanding or understanding["user_revision"] != len(state["replies"]):
        raise ValueError("需要当前版本的任务理解")
    goals = {g["id"]: g for g in understanding["goals"]}
    assessments = args["assessments"]
    if sorted(a["goal_id"] for a in assessments) != sorted(goals):
        raise ValueError("必须且只能评价每个目标一次")
    facts = {}
    outcomes = []
    for a in assessments:
        goal = goals[a["goal_id"]]
        kind = goal["kind"]
        status = a["status"]
        indices = a["evidence"]
        if any(type(i) is not int or not 0 <= i < len(state["steps"]) for i in indices):
            raise ValueError("证据引用不存在")
        steps = [state["steps"][i] for i in sorted(set(indices))]
        if any(
            not s["result"].get("success")
            or s["tool"] in {"update_task", "recall_memory", "ask_clarification"}
            for s in steps
        ):
            raise ValueError("任务理解或历史摘要不能证明当前操作")
        selected = steps
        if status in {"unsupported", "unfulfilled"}:
            if status == "unsupported" and kind != "unsupported":
                raise ValueError("目标类型与不支持结论不符")
        elif kind == "read" and status == "fulfilled":
            expected = normalize(goal["tool"], goal["args"])
            selected = [
                s
                for s in steps
                if s["tool"] == goal["tool"] and matches(expected, s["args"])
            ]
            if not selected:
                raise ValueError("缺少匹配查询证据")
        elif kind == "write" and status == "fulfilled":
            effect = write_evidence(goal, steps, receipts)
            if not effect:
                raise ValueError("缺少匹配的实际提交回执")
            selected = [state["steps"][effect["seq"]]]
        elif kind == "ensure_config" and status in {"fulfilled", "not_needed"}:
            read = ensure_read(goal, steps, state["steps"])
            if not read:
                raise ValueError("必须读取并确认当前配置达到目标值")
            effect = write_evidence(goal, state["steps"], receipts)
            if (status == "not_needed") != (effect is None):
                raise ValueError("无需修改与实际提交记录不符")
            if effect and read["seq"] < effect["seq"]:
                raise ValueError("修改后需要重新查询")
            selected = [read]
        elif kind == "verify" and status == "fulfilled":
            parent = goals.get(goal["write_goal_id"])
            if not parent or parent["kind"] not in {"write", "ensure_config"}:
                raise ValueError("核验必须关联写目标")
            effect = write_evidence(parent, state["steps"], receipts)
            if effect:
                if not verified_effect(
                    effect, [s for s in steps if read_is_current(s, state["steps"])]
                ):
                    raise ValueError("缺少匹配批次/配置的写后核验证据")
            elif parent["kind"] != "ensure_config" or not ensure_read(
                parent, steps, state["steps"]
            ):
                raise ValueError("没有可核验的操作")
        else:
            raise ValueError("目标与结论类型不符")
        facts[goal["id"]] = fact_sentence(goal, a, selected)
        if (
            kind == "read"
            and status == "fulfilled"
            and not read_is_current(selected[-1], state["steps"])
        ):
            facts[goal["id"]] = f"步骤{selected[-1]['seq']}的历史读取：" + facts[goal["id"]]
        outcomes.append({**a, "source_ids": goal["source_ids"]})
    result = finalize_outcome(state, receipts, check_request=False)
    result["observations"] = [
        o
        for o in result["observations"]
        if o["tool"] not in {"update_task", "recall_memory"}
    ]
    result.update(
        goals=outcomes,
        completion_scope="validated_model_goals",
        semantic_goal_accuracy="requires_independent_evaluation",
        unfulfilled=[
            a["goal_id"]
            for a in assessments
            if a["status"] in {"unsupported", "unfulfilled"}
        ],
    )
    result["message"], result["answer_fallback"] = render_answer(
        args["answer_template"], facts
    )
    return result
