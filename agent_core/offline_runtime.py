"""Build the existing graph with local platform substitutes only."""
from agent_core.governed_agent import GovernedAgent
from agent_core.langgraph_agent.metadata import default_metadata_registry, ToolMetadata, SkillMetadata
from agent_core.mock_platforms import MockPlatforms


class MockTool:
    def __init__(self, name, platforms):
        self.name = name
        self.platforms = platforms

    def invoke(self, payload):
        params = dict(payload)
        return self.platforms.execute(self.name, params, params.pop("context", {}))


def build_offline_agent(path=".mock_state/platforms.sqlite", llm=None):
    registry = default_metadata_registry()
    additions = [
        ("add_gift_to_backpack", "向用户背包发放测试礼物", "execute", ["user_id", "gift_id", "quantity"], "database"),
        ("query_gift_records", "查询本地模拟礼物记录，可按 user_id 或 batch_id 过滤", "query", [], "database"),
        ("query_event", "查询本地模拟活动时间", "query", ["event_id"], "test_admin_backend"),
        ("query_script_runs", "查询模拟脚本执行记录", "query", [], "database"),
    ]
    for name, desc, kind, required, platform in additions:
        registry.skills[name] = SkillMetadata(name, desc, kind, [name])
        registry.tools[name] = ToolMetadata(name, desc, platform, "mock_executor", required_params=required)
    platforms = MockPlatforms(path)
    names = set(registry.tools) | {"script_scan", "script_read", "script_run", "backend_feature"}
    agent = GovernedAgent(tools={name: MockTool(name, platforms) for name in names}, llm=llm, metadata_registry=registry)
    agent.mock_platforms = platforms
    agent.runtime_mode = "mock"
    if hasattr(agent.llm, "tool_catalog"):
        agent.llm.tool_catalog = [
            {"tool_name": t.tool_name, "description": t.description, "required_params": t.required_params,
             "conditional_required_params": t.conditional_required_params}
            for t in registry.platform_tools()
        ]
    return agent
