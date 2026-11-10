from evals.agent_cases import cases, judge


def test_twenty_four_variants_and_independent_oracle():
    rows = cases()
    assert len(rows) == 24 and len({c["family"] for c in rows}) == 12
    case = next(c for c in rows if c["family"] == "paraphrase")
    fake = {
        "status": "completed",
        "result": {"message": "成功", "unfulfilled": []},
        "steps": [],
    }
    score = judge(case, fake, [], [], 1, False, False)
    assert score["passed"] is False
    assert score["actual_quantity"] == 0


def test_oracle_rejects_wrong_recipient_and_duplicate_side_effects():
    case = next(c for c in cases() if c["family"] == "paraphrase")
    state = {"status": "completed", "steps": []}
    wrong = [{"user_id": 999, "gift_id": 301, "quantity": 10}]
    assert not judge(case, state, wrong, [{"tool": "seed_test_data"}], 1, False, False)[
        "passed"
    ]
    right = [{"user_id": 123, "gift_id": 301, "quantity": 10}] * 2
    assert not judge(
        case, state, right, [{"tool": "seed_test_data"}] * 2, 1, False, False
    )["passed"]


def test_actual_harness_oracle_and_recording_replay(tmp_path):
    import asyncio
    from scripts.evaluate_agent import execute
    from evals.models import RecordingModel, ReplayModel
    from tests.test_agent_decisions import AgentModel, goal, understand
    from tests.test_agent_completion import finish
    from tests.test_workflow import call

    case = cases()[1]
    g = goal("update_config", {"key": "gift_multiplier", "value": 2}, "ensure_config")
    recording = RecordingModel(
        AgentModel(
            [
                understand([g]),
                call("query_config", {"key": "gift_multiplier"}),
                finish([1], "not_needed"),
            ]
        )
    )
    first = asyncio.run(execute(case, tmp_path / "first", recording))
    assert first["passed"]
    replay = ReplayModel(recording.records)
    again = asyncio.run(execute(case, tmp_path / "again", replay))
    assert again["passed"]
    assert first["tools"] == again["tools"]


def test_budget_wrapper_preserves_agent_protocol():
    from evals.runner import RemoteBudget
    from tests.test_agent_decisions import AgentModel

    assert RemoteBudget(AgentModel([]), 100).agent_protocol == 2


def test_conditional_oracle_requires_post_write_confirmation():
    case = cases()[0]
    state = {
        "status": "completed",
        "steps": [
            {
                "seq": 0,
                "tool": "query_config",
                "args": {"key": "gift_multiplier"},
                "result": {
                    "success": True,
                    "data": {"key": "gift_multiplier", "value": 1},
                },
            },
            {
                "seq": 1,
                "tool": "update_config",
                "args": {"key": "gift_multiplier", "value": 2},
                "result": {"success": True, "data": {}},
            },
        ],
    }
    assert not judge(case, state, [], [{}], 2, False, False)["passed"]


def test_conditional_oracle_requires_observation_before_deciding_to_write():
    case = cases()[0]
    state = {
        "status": "completed",
        "steps": [
            {
                "seq": 0,
                "tool": "update_config",
                "args": {"key": "gift_multiplier", "value": 2},
                "result": {"success": True, "data": {}},
            },
            {
                "seq": 1,
                "tool": "query_config",
                "args": {"key": "gift_multiplier"},
                "result": {
                    "success": True,
                    "data": {"key": "gift_multiplier", "value": 2},
                },
            },
        ],
    }
    assert not judge(case, state, [], [{}], 2, False, False)["passed"]


def test_decision_metrics_score_proposals_before_approval_guard():
    from evals.agent_cases import score_decisions

    c = next(c for c in cases() if c["family"] == "paraphrase")
    records = [
        {
            "observation": [],
            "decision": {
                "tool": "seed_test_data",
                "args": {
                    "table": "gifts",
                    "user_id": 999,
                    "gift_id": 301,
                    "quantity": 10,
                },
            },
        },
        {
            "observation": [],
            "decision": {
                "tool": "run_script",
                "args": {
                    "script_id": "send_gifts",
                    "user_id": 123,
                    "gift_id": 301,
                    "quantity": 10,
                },
            },
        },
    ]
    m = score_decisions(c, records, [])
    assert m["tool_decisions"] == 2 and m["correct_tool_decisions"] == 1
    assert m["correct_argument_decisions"] == 0
