import asyncio
import json

import httpx
import pytest

from agent_core.layers.local_config import LocalConfigLayer
from agent_core.langgraph_agent.llm import DeepSeekLLM
from agent_core.offline_runtime import build_offline_agent
from agent_core.mock_platforms import MockPlatforms


def run(agent, text, **context):
    return asyncio.run(agent.ainvoke(text, {"operator": "tester", "session_id": "test", **context}))


def config(tmp_path, **settings):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"secrets": settings}))
    return LocalConfigLayer(str(path))


def test_confirmed_gift_is_persisted_and_queryable_after_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    agent = build_offline_agent(path, llm=DeepSeekLLM(config(tmp_path, llm_mode="offline")))
    result = run(agent, "给用户123发放专属礼物20001")
    assert result["code"] == "CONFIRM_REQUIRED"
    assert MockPlatforms(path).snapshot("gifts") == []
    result = run(agent, "确认执行")
    assert result["status"] == "success"
    assert result["data"]["runtime_mode"] == "mock"
    rows = MockPlatforms(path).snapshot("gifts")
    assert len(rows) == 1
    assert rows[0]["user_id"] == 123
    assert rows[0]["gift_id"] == 20001
    queried = run(agent, "查询用户123的礼物记录")
    assert queried["data"]["rows"][0]["gift_id"] == 20001


def execute_approved(mock, tool, params, context):
    action = mock.prepare(tool, params, context)
    mock.actions.approve(action["action_id"], context)
    return mock.execute(tool, params, {**context, "action_id": action["action_id"]})


def test_backend_and_script_change_mock_state_only(tmp_path):
    mock = MockPlatforms(tmp_path / "state.sqlite")
    context = {"execute_confirmed": True}
    result = execute_approved(mock, "shift_event_time", {"event_id": 42, "event_to_time": "明天"}, context)
    assert result["success"]
    assert mock.snapshot("events")[0]["event_to_time"] == "明天"
    result = execute_approved(mock, "send_gifts_to_one_room", {"gift_id": 101, "user_id": 123, "room_id": 888, "num": 2, "count": 3}, context)
    assert result["success"]
    assert sum(row["quantity"] for row in mock.snapshot("gifts")) == 6
    assert len(mock.snapshot("script_runs")) == 1


@pytest.mark.parametrize("fault,code", [("f_403", "PERMISSION_DENIED"), ("f_5xx", "TRANSIENT"), ("f_timeout", "TIMEOUT")])
def test_injected_failure_never_mutates_state(tmp_path, fault, code):
    mock = MockPlatforms(tmp_path / "state.sqlite")
    result = execute_approved(mock, "add_gift_to_backpack", {"user_id": 123, "gift_id": 301, "quantity": 10}, {"execute_confirmed": True, "fault_id": fault})
    assert result["code"] == code
    assert not result["success"]
    assert mock.snapshot("gifts") == []


def test_partial_write_is_reported_and_reset_is_repeatable(tmp_path):
    mock = MockPlatforms(tmp_path / "state.sqlite")
    for _ in range(2):
        mock.reset()
        result = execute_approved(mock, "add_gift_to_backpack", {"user_id": 123, "gift_id": 301, "quantity": 10}, {"execute_confirmed": True, "fault_id": "f_halfseed"})
        assert result["status"] == "partial_success"
        assert not result["success"]
        assert result["data"]["expected"] == 10
        assert result["data"]["actual"] == 5
        assert sum(r["quantity"] for r in mock.snapshot("gifts")) == 5


@pytest.mark.parametrize("context", [{}, {"execute_confirmed": True, "env": "prod"}, {"execute_confirmed": True, "allowed_tools": []}])
def test_mock_write_guards_cannot_be_bypassed(tmp_path, context):
    mock = MockPlatforms(tmp_path / "state.sqlite")
    result = mock.execute("add_gift_to_backpack", {"user_id": 123, "gift_id": 301, "quantity": 10}, context)
    assert not result["success"]
    assert mock.snapshot("gifts") == []


def test_invalid_and_unknown_mock_actions_fail_closed(tmp_path):
    mock = MockPlatforms(tmp_path / "state.sqlite")
    for tool, params in [("add_gift_to_backpack", {"user_id": 123, "gift_id": 301, "quantity": -1}), ("db_write", {"sql": "DELETE FROM gifts"}), ("script_run", {"script_path": "../../real.py"})]:
        assert not mock.execute(tool, params, {"execute_confirmed": True})["success"]
    assert mock.snapshot("gifts") == []


def test_llm_config_reads_uppercase_file_keys(tmp_path):
    settings = config(tmp_path, LLM_API_KEY="test-key")
    assert settings.get_secret("llm_api_key", "LLM_API_KEY") == "test-key"


def test_compatible_llm_uses_configured_endpoint_model_and_key(tmp_path):
    settings = config(tmp_path, llm_mode="remote", llm_api_key="test-key", llm_base_url="https://llm.example.test/custom/v1", llm_model="deepseek-v4.1-flash")
    def handler(request):
        assert str(request.url) == "https://llm.example.test/custom/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4.1-flash"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"intent":"chat","is_chat":true,"params":{}}'}}]})
    llm = DeepSeekLLM(settings, transport=httpx.MockTransport(handler))
    result = asyncio.run(llm.classify_intent("你好"))
    assert result["is_chat"] is True


def test_remote_auth_error_does_not_silently_fall_back(tmp_path):
    settings = config(tmp_path, llm_mode="remote", llm_api_key="test-key", llm_base_url="https://llm.example.test/v1", llm_model="example-model")
    llm = DeepSeekLLM(settings, transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"error": "invalid key"})))
    agent = build_offline_agent(tmp_path / "state.sqlite", llm=llm)
    result = run(agent, "查询用户123的礼物记录")
    assert result["code"] == "LLM_ERROR"
    assert result["success"] is False
    assert result["data"]["llm_mode"] == "remote"


def test_http_entry_supports_existing_url_without_old_platform_startup(tmp_path):
    from api.offline_server import create_app
    agent = build_offline_agent(tmp_path / "state.sqlite", llm=DeepSeekLLM(config(tmp_path, llm_mode="offline")))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(agent)), base_url="http://local.test") as client:
            health = (await client.get("/health")).json()
            assert health["runtime_mode"] == "mock"
            assert health["llm_mode"] == "offline"
            context = {"operator": "tester", "session_id": "http-case"}
            first = (await client.post("/agent/execute", json={"business_code": "testops", "user_input": "给用户123发10个礼物301到背包", "context": context})).json()
            assert first["code"] == "CONFIRM_REQUIRED"
            approved = (await client.post("/agent/execute", json={"user_input": "确认执行", "context": context})).json()
            assert approved["data"]["actual"] == 10
            rows = (await client.post("/agent/langgraph/execute", json={"user_input": "查询用户123的礼物记录", "context": context})).json()
            assert rows["data"]["rows"][0]["quantity"] == 10
            unknown = await client.post("/agent/execute", json={"business_code": "unknown", "user_input": "你好"})
            assert unknown.status_code == 400
    asyncio.run(scenario())


def test_opencode_transport_supplies_stable_session_routing_header(tmp_path):
    settings = config(tmp_path, llm_mode="remote", OPENCODE_API_KEY="test-key", OPENCODE_BASE_URL="https://opencode.ai/zen/go/v1", OPENCODE_MODEL="deepseek-v4.1-flash")
    sessions = []
    def handler(request):
        sessions.append(request.headers.get("x-opencode-session"))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"intent":"chat","is_chat":true}'}}]})
    llm = DeepSeekLLM(settings, transport=httpx.MockTransport(handler))
    async def scenario():
        for _ in range(2):
            await llm.classify_intent("你好", {"operator": "tester", "session_id": "abc"})
        await llm.classify_intent("你好", {"operator": "tester", "session_id": "other"})
    asyncio.run(scenario())
    assert sessions[0] and sessions[0] == sessions[1]
    assert sessions[2] != sessions[0]


def test_confirmation_does_not_authorize_next_write_in_reused_context(tmp_path):
    agent = build_offline_agent(tmp_path / "state.sqlite", llm=DeepSeekLLM(config(tmp_path, llm_mode="offline")))
    context = {"operator": "tester", "session_id": "same-context"}
    async def scenario():
        await agent.ainvoke("给用户123发放专属礼物20001", context)
        assert (await agent.ainvoke("确认执行", context))["success"]
        second = await agent.ainvoke("给用户123发放专属礼物20002", context)
        assert second["code"] == "CONFIRM_REQUIRED"
        assert "execute_confirmed" not in context
    asyncio.run(scenario())


def test_offline_event_timestamp_and_script_history(tmp_path):
    agent = build_offline_agent(tmp_path / "state.sqlite", llm=DeepSeekLLM(config(tmp_path, llm_mode="offline")))
    run(agent, "把活动42调整时间，调整到2026-11-10 18:30:00")
    assert run(agent, "确认执行")["success"]
    result = run(agent, "查询活动42的时间")
    assert result["data"]["rows"][0]["event_to_time"] == "2026-11-10 18:30:00"
    run(agent, "用用户123给直播间8888送礼物10001，每次2个，执行3次")
    assert run(agent, "确认执行")["success"]
    result = run(agent, "查询脚本执行记录")
    assert result["success"]
    assert result["data"]["rows"][0]["quantity"] == 6
