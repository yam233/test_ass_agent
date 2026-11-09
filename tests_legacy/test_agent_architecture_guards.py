import asyncio

from agent_core.async_skill_agent import AsyncSkillAgent
from agent_core.helpers.batch_query_executor import BatchQueryExecutor
from agent_core.layers import LocalConfigLayer, SafetyLayer
from agent_core.langgraph_agent import LangGraphAgent
from agent_core.langgraph_agent.compat import BaseTool
from agent_core.langgraph_agent.metadata import default_metadata_registry
from agent_core.langgraph_agent.tools import DBQueryTool, ScriptRunTool
from agent_core.managers.param_validator import ParamValidator
from agent_core.result_status import STATUS_FAILED, STATUS_PARTIAL_SUCCESS, STATUS_SUCCESS, status_from_counts
from agent_core.skills.standard import (
    BackendMetadataSkill,
    BackendGiftIssueSkill,
    DatabaseQuerySkill,
    TestScriptSkill,
)
from agent_plugins.testops.skills.skill_factory import SkillFactory
from utils.config_loader import ConfigLoader
from business_logic.common.universal_query_executor import UniversalQueryExecutor
from business_logic.common import db as common_db


def test_param_validator_rejects_invalid_array_and_object_types():
    schema = {
        "user_ids": {"type": "array", "required": True},
        "gift_nums": {"type": "object", "required": True},
    }

    result = ParamValidator.validate(
        {"user_ids": 9075566, "gift_nums": "301:10"},
        schema,
    )

    assert result["valid"] is False
    assert "参数 user_ids 类型错误" in result["errors"][0]
    assert "参数 gift_nums 类型错误" in result["errors"][1]


def test_param_validator_normalizes_comma_separated_arrays():
    schema = {"user_ids": {"type": "array", "required": True}}

    result = ParamValidator.validate({"user_ids": "9075566,9075567"}, schema)

    assert result["valid"] is True
    assert result["params"]["user_ids"] == ["9075566", "9075567"]


def test_param_validator_normalizes_boolean_strings():
    schema = {"sync_latest": {"type": "boolean", "required": False}}

    result = ParamValidator.validate({"sync_latest": "true"}, schema)

    assert result["valid"] is True
    assert result["params"]["sync_latest"] is True


def test_status_from_counts_distinguishes_partial_success():
    assert status_from_counts(2, 0) == STATUS_SUCCESS
    assert status_from_counts(2, 1) == STATUS_PARTIAL_SUCCESS
    assert status_from_counts(0, 3) == STATUS_FAILED


def test_batch_executor_reports_failed_items():
    async def run_query(params, index):
        if params["user_id"] == 2:
            return {"success": False, "message": "用户不存在", "data": {}}
        return {"success": True, "message": "ok", "data": {"user_id": params["user_id"]}}

    result = asyncio.run(
        BatchQueryExecutor.run_batch_queries(
            [{"user_id": 1}, {"user_id": 2}],
            run_query,
            label_param="user_id",
        )
    )

    assert result["data"]["success_count"] == 1
    assert result["data"]["failed_count"] == 1
    assert result["data"]["items"][1]["status"] == "failed"


def test_execute_confirmation_guard_defaults_on():
    agent = AsyncSkillAgent.__new__(AsyncSkillAgent)
    agent.intent_safety_config = {"execute_need_confirm": True}

    assert agent._execute_requires_confirmation(
        {"skill_type": "execute", "skill_name": "add_backpack_gift"},
        {},
    ) is True

    assert agent._execute_requires_confirmation(
        {"skill_type": "execute", "skill_name": "add_backpack_gift"},
        {"execute_confirmed": True},
    ) is False

    assert agent._execute_requires_confirmation(
        {"skill_type": "query", "skill_name": "query_gift_info"},
        {},
    ) is False


def test_safety_layer_opens_query_and_blocks_unconfirmed_execute():
    safety = SafetyLayer()

    query_decision = safety.evaluate({"skill_type": "query"}, {"operator": "tester", "env": "uat"})
    assert query_decision.allowed is True
    assert query_decision.need_confirm is False

    execute_decision = safety.evaluate({"skill_type": "execute", "risk_level": "medium"}, {"operator": "tester", "env": "uat"})
    assert execute_decision.allowed is True
    assert execute_decision.need_confirm is True

    confirmed = safety.evaluate({"skill_type": "execute"}, {"execute_confirmed": True, "env": "uat"})
    assert confirmed.allowed is True
    assert confirmed.need_confirm is False


def test_database_query_skill_rejects_write_sql():
    ok, _ = DatabaseQuerySkill.validate_sql("SELECT * FROM user LIMIT 1")
    assert ok is True

    ok, reason = DatabaseQuerySkill.validate_sql("DELETE FROM user WHERE id = 1")
    assert ok is False
    assert "仅允许" in reason


def test_common_execute_query_blocks_write_sql_before_connection(monkeypatch):
    def fail_connection(db_type="live"):
        raise AssertionError("connection should not be opened for invalid SQL")

    monkeypatch.setattr(common_db, "get_connection", fail_connection)

    try:
        common_db.execute_query("UPDATE user SET name = 'x'")
    except ValueError as exc:
        assert "仅允许" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_database_query_skill_rejects_risky_mongo_query():
    ok, reason = DatabaseQuerySkill.validate_mongo_query({"$where": "sleep(1)"})

    assert ok is False
    assert "高风险" in reason


def test_backend_gift_issue_requires_core_params():
    ok, reason = BackendGiftIssueSkill.validate({"user_id": 1})
    assert ok is False
    assert "礼物参数" in reason


def test_backend_gift_issue_normalizes_target_and_type():
    params = BackendGiftIssueSkill.normalize(
        {"target_id": 9075566, "gift_id": 20123},
        location="exclusive_tab",
    )

    assert params["user_id"] == 9075566
    assert params["gift_type"] == "user_exclusive"
    assert params["issue_location"] == "exclusive_tab"
    assert BackendGiftIssueSkill.validate(params)[0] is True


def test_backend_gift_issue_allows_batch_gift_params():
    params = BackendGiftIssueSkill.normalize(
        {"user_id": 9075566, "gift_ids": [301, 302]},
        location="backpack",
    )

    assert BackendGiftIssueSkill.validate(params)[0] is True


def test_backend_metadata_skill_searches_entries():
    skill = BackendMetadataSkill([
        {"title": "随机礼物后台", "url": "https://example.test/random-gift"},
        {"title": "外观配置", "url": "https://example.test/appearance"},
    ])

    result = skill.search("随机礼物")

    assert result["success"] is True
    assert len(result["data"]["features"]) == 1
    assert result["data"]["features"][0]["title"] == "随机礼物后台"


def test_universal_query_blocks_write_actions():
    executor = UniversalQueryExecutor("testops")

    result = executor.execute(
        {"entity": "user", "action": "delete", "filters": {"user_id": 1}},
        handlers={}
    )

    assert result["success"] is False
    assert "只读动作" in result["message"]


def test_universal_query_returns_metadata_without_handler():
    executor = UniversalQueryExecutor("testops")

    result = executor.execute(
        {"entity": "用户", "action": "metadata"},
        handlers={}
    )

    assert result["success"] is True
    assert result["data"]["items"][0]["entity"] == "user"


def test_test_script_execute_requires_approval(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "case.py"
    script.write_text("print('ok')", encoding="utf-8")

    skill = TestScriptSkill(str(repo))
    result = skill.execute_script("case.py", approved=False)

    assert result["success"] is False
    assert result["status"] == "blocked"


def test_langgraph_base_tool_compat_exposes_invoke():
    class EchoTool(BaseTool):
        name = "echo"
        description = "echo"

        def _run(self, value=""):
            return {"success": True, "message": value, "data": {}}

    result = EchoTool().invoke({"value": "ok"})

    assert result["success"] is True
    assert result["message"] == "ok"


def test_langgraph_db_query_tool_blocks_write_sql_before_execution():
    result = DBQueryTool().invoke({"sql": "UPDATE user SET name = 'x'"})

    assert result["success"] is False
    assert result["status"] == "blocked"
    assert "仅允许" in result["message"]


def test_langgraph_script_run_tool_requires_confirmation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "case.py").write_text("print('ok')", encoding="utf-8")

    result = ScriptRunTool(repo_path=str(repo)).invoke(
        {"script_path": "case.py", "context": {"env": "uat"}}
    )

    assert result["success"] is False
    assert result["status"] == "blocked"
    assert result["data"]["need_confirm"] is True


def test_langgraph_agent_routes_chat_without_external_llm():
    agent = LangGraphAgent(tools={})

    result = asyncio.run(agent.ainvoke("你好", context={"env": "uat"}))

    assert result["success"] is True
    assert result["tool_name"] == "native_chat"


def test_langgraph_agent_routes_backend_metadata_tool():
    class FakeTool:
        name = "backend_feature"

        def invoke(self, payload):
            return {
                "success": True,
                "message": "找到 1 个后台入口",
                "data": {"features": [{"title": "礼物后台", "url": "https://example.test"}]},
            }

    agent = LangGraphAgent(tools={"backend_feature": FakeTool()})

    result = asyncio.run(agent.ainvoke("礼物后台地址", context={"env": "uat"}))

    assert result["success"] is True
    assert result["data"]["features"][0]["title"] == "礼物后台"


def test_langgraph_agent_blocks_script_execution_without_confirmation():
    class ShouldNotRunTool:
        name = "script_run"

        def invoke(self, payload):
            raise AssertionError("tool should not run before permission confirmation")

    agent = LangGraphAgent(tools={"script_run": ShouldNotRunTool()})

    result = asyncio.run(agent.ainvoke("执行脚本 case.py", context={"env": "uat"}))

    assert result["success"] is False
    assert result["status"] == "blocked"
    assert result["data"]["need_confirm"] is True
    assert result["code"] == "CONFIRM_REQUIRED"


def test_langgraph_agent_clarifies_missing_script_param_and_resumes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "case.py").write_text("print('ok')", encoding="utf-8")
    agent = LangGraphAgent(tools={"script_read": ScriptRunTool(repo_path=str(repo))})

    first = asyncio.run(agent.ainvoke("读取脚本源码", context={"env": "uat", "operator": "alice", "session_id": "s1"}))

    assert first["success"] is False
    assert first["code"] == "NEED_MORE_INFO"
    assert first["data"]["missing_params"] == ["script_path"]


def test_langgraph_memory_is_isolated_by_operator():
    agent = LangGraphAgent(tools={})

    asyncio.run(agent.ainvoke("读取脚本源码", context={"env": "uat", "operator": "alice", "session_id": "s1"}))
    asyncio.run(agent.ainvoke("你好", context={"env": "uat", "operator": "bob", "session_id": "s1"}))

    assert agent.memory.get_pending({"operator": "alice", "session_id": "s1"}) is not None
    assert agent.memory.get_pending({"operator": "bob", "session_id": "s1"}) is None


def test_langgraph_agent_wraps_tool_exceptions():
    class BrokenTool:
        name = "backend_feature"

        def invoke(self, payload):
            raise RuntimeError("boom")

    agent = LangGraphAgent(tools={"backend_feature": BrokenTool()})

    result = asyncio.run(agent.ainvoke("礼物后台地址", context={"env": "uat", "operator": "tester"}))

    assert result["success"] is False
    assert result["code"] == "TOOL_EXECUTION_ERROR"
    assert result["request_id"]
    assert result["data"]["trace"]["nodes"]


def test_langgraph_permission_honors_tool_whitelist():
    class ShouldNotRunTool:
        name = "backend_feature"

        def invoke(self, payload):
            raise AssertionError("tool should not run when whitelist denies it")

    agent = LangGraphAgent(tools={"backend_feature": ShouldNotRunTool()})

    result = asyncio.run(agent.ainvoke(
        "礼物后台地址",
        context={"env": "uat", "operator": "tester", "allowed_tools": ["script_scan"]},
    ))

    assert result["success"] is False
    assert result["code"] == "PERMISSION_DENIED"


def test_metadata_registry_uses_tool_platform_without_server_name():
    registry = default_metadata_registry()

    tool_name = registry.resolve_tool_name({"intent": "event_time_shift", "params": {"event_id": 10001}})
    tool = registry.get_tool(tool_name)

    assert tool_name == "shift_event_time"
    assert tool.platform == "test_admin_backend"
    assert tool.executor == "http_api_executor"
    assert not hasattr(tool, "server_name")


def test_langgraph_metadata_routes_exclusive_gift_to_database_executor():
    agent = LangGraphAgent()

    result = asyncio.run(agent.ainvoke(
        "给用户123发放专属礼物20001",
        context={"env": "uat", "operator": "tester", "execute_confirmed": True},
    ))

    assert result["success"] is True
    assert result["status"] == "planned"
    assert result["data"]["skill_name"] == "execute_gift_issue"
    assert result["data"]["tool_name"] == "add_gift_to_exclusive_tab"
    assert result["data"]["platform"] == "database"
    assert result["data"]["executor"] == "database_sql_executor"
    assert result["data"]["table_name"] == "live_custom"


def test_langgraph_metadata_routes_event_shift_to_backend_executor():
    agent = LangGraphAgent()

    result = asyncio.run(agent.ainvoke(
        "把活动10001的时间偏移到明天",
        context={"env": "uat", "operator": "tester", "execute_confirmed": True},
    ))

    assert result["success"] is True
    assert result["status"] == "planned"
    assert result["data"]["skill_name"] == "event_time_shift"
    assert result["data"]["tool_name"] == "shift_event_time"
    assert result["data"]["platform"] == "test_admin_backend"
    assert result["data"]["executor"] == "http_api_executor"
    assert result["data"]["request_params"]["eventId"] == 10001
    assert result["data"]["request_params"]["targetTime"] == "明天"


def test_langgraph_metadata_routes_send_gifts_to_script_executor():
    agent = LangGraphAgent()

    result = asyncio.run(agent.ainvoke(
        "用用户123给直播间8888送礼物10001，送100次",
        context={"env": "uat", "operator": "tester", "execute_confirmed": True},
    ))

    assert result["success"] is True
    assert result["status"] == "planned"
    assert result["data"]["skill_name"] == "send_gifts"
    assert result["data"]["tool_name"] == "send_gifts_to_one_room"
    assert result["data"]["platform"] == "test_script"
    assert result["data"]["executor"] == "script_executor"
    assert "gift/send_gifts_to_one_room.py" == result["data"]["script"]["path"]
    assert "--gift-id" in result["data"]["args"]


def test_test_script_scan_and_read(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "case.py"
    script.write_text("print('ok')", encoding="utf-8")

    skill = TestScriptSkill(str(repo))
    scan = skill.scan_scripts()
    read = skill.read_script("case.py")

    assert scan["success"] is True
    assert scan["data"]["scripts"][0]["relative_path"] == "case.py"
    assert read["success"] is True
    assert "print('ok')" in read["data"]["content"]


def test_script_skills_can_be_created_from_registry():
    skills_registry = ConfigLoader.load_business_config("testops", "skills_registry.json")
    mcp_registry = ConfigLoader.load_business_config("testops", "mcp_registry.json")
    script_skill_names = {"scan_test_scripts", "read_test_script", "execute_test_script"}

    created = []
    for skill_config in skills_registry["skills"]:
        if skill_config.get("skill_name") in script_skill_names:
            created.append(SkillFactory.create_skill(skill_config, mcp_registry, "testops"))

    assert len(created) == 3


def test_local_config_redacts_secrets(tmp_path):
    cfg = tmp_path / "agent_secrets.json"
    cfg.write_text(
        '{"secrets": {"DEEPSEEK_API_KEY": "secret"}, "gitlab": {"token": "abc", "repo_url": "x"}}',
        encoding="utf-8",
    )

    layer = LocalConfigLayer(str(cfg))

    assert layer.get_secret("DEEPSEEK_API_KEY") == "secret"
    assert layer.redacted()["secrets"]["DEEPSEEK_API_KEY"] == "***"
    assert layer.redacted()["gitlab"]["token"] == "***"
