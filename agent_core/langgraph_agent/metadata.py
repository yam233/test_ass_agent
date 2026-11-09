"""Metadata registry for platform-based skill/tool execution."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SkillMetadata:
    skill_name: str
    description: str
    skill_type: str
    tool_candidates: List[str]
    match_keywords: List[str] = field(default_factory=list)
    param_schema: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ToolMetadata:
    tool_name: str
    description: str
    platform: str
    executor: str
    service: str = ""
    required_params: List[str] = field(default_factory=list)
    conditional_required_params: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def missing_params(self, params: Dict[str, Any]) -> List[str]:
        missing = [
            name for name in self.required_params
            if params.get(name) in (None, "", [], {})
        ]
        for rule in self.conditional_required_params:
            if self._condition_matches(rule.get("when", ""), params):
                for name in rule.get("required", []):
                    if params.get(name) in (None, "", [], {}) and name not in missing:
                        missing.append(name)
        return missing

    @staticmethod
    def _condition_matches(condition: str, params: Dict[str, Any]) -> bool:
        condition = (condition or "").strip().lower()
        gift_id = str(params.get("gift_id") or "")
        if condition == "gift_id startswith 2":
            return gift_id.startswith("2")
        if condition == "gift_id startswith 7":
            return gift_id.startswith("7")
        if condition == "gift_id startswith 8":
            return gift_id.startswith("8")
        return False


@dataclass
class PlatformMetadata:
    platform: str
    description: str
    executor: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class PlatformMetadataRegistry:
    """In-memory metadata registry for the three platform model."""

    def __init__(
        self,
        skills: Optional[List[SkillMetadata]] = None,
        tools: Optional[List[ToolMetadata]] = None,
        platforms: Optional[List[PlatformMetadata]] = None,
    ):
        self.skills = {item.skill_name: item for item in (skills or [])}
        self.tools = {item.tool_name: item for item in (tools or [])}
        self.platforms = {item.platform: item for item in (platforms or [])}

    def get_skill(self, skill_name: str) -> Optional[SkillMetadata]:
        return self.skills.get(skill_name)

    def get_tool(self, tool_name: str) -> Optional[ToolMetadata]:
        return self.tools.get(tool_name)

    def get_platform(self, platform: str) -> Optional[PlatformMetadata]:
        return self.platforms.get(platform)

    def resolve_tool_name(self, intent: Dict[str, Any]) -> str:
        tool_name = intent.get("tool_name") or ""
        if tool_name in self.tools:
            return tool_name
        skill = self.get_skill(intent.get("intent") or intent.get("skill_name") or tool_name)
        if not skill:
            return tool_name or intent.get("intent", "")
        if len(skill.tool_candidates) == 1:
            return skill.tool_candidates[0]
        params = intent.get("params") or {}
        text_hint = " ".join(str(v) for v in [intent.get("intent"), tool_name, params])
        for candidate in skill.tool_candidates:
            if candidate in text_hint:
                return candidate
        return skill.tool_candidates[0]

    def platform_tools(self) -> List[ToolMetadata]:
        return list(self.tools.values())


def default_metadata_registry() -> PlatformMetadataRegistry:
    return PlatformMetadataRegistry(
        platforms=[
            PlatformMetadata(
                platform="database",
                description="数据库执行平台，维护库表字段、SQL模板和业务语义",
                executor="database_sql_executor",
                metadata={
                    "tables": {
                        "live_custom": {
                            "table_url": "数据库后台或管理平台链接",
                            "description": "专属 tab 礼物权益表",
                            "fields": {
                                "custom_id": "礼物 ID",
                                "element_id": "用户 ID 或直播间 ID",
                                "custom_type": "权益归属类型，3=用户，2=直播间",
                                "start_time": "生效时间",
                                "end_time": "过期时间",
                                "delete_time": "删除时间，0=有效",
                            },
                        }
                    }
                },
            ),
            PlatformMetadata(
                platform="test_admin_backend",
                description="测试工具后台执行平台，维护接口、鉴权、参数映射和返回解析",
                executor="http_api_executor",
                metadata={"auth_provider": "test_admin_backend"},
            ),
            PlatformMetadata(
                platform="test_script",
                description="测试脚本执行平台，维护仓库、分支、脚本路径和执行限制",
                executor="script_executor",
                metadata={
                    "execution_policy": {
                        "sync_before_run": True,
                        "timeout_seconds": 120,
                        "max_concurrency": 2,
                        "allowed_script_dirs": ["gift", "event", "room"],
                    }
                },
            ),
        ],
        skills=[
            SkillMetadata(
                skill_name="execute_gift_issue",
                description="礼物发放能力，支持专属礼物、背包礼物、免费礼物等",
                skill_type="execute",
                tool_candidates=["add_gift_to_exclusive_tab"],
                match_keywords=["发放礼物", "专属礼物", "背包礼物", "免费礼物"],
                param_schema={
                    "gift_id": {"type": "integer", "required": True},
                    "user_id": {"type": "integer", "required": False},
                    "room_id": {"type": "integer", "required": False},
                    "duration_days": {"type": "integer", "required": False},
                },
            ),
            SkillMetadata(
                skill_name="event_time_shift",
                description="偏移活动时间",
                skill_type="execute",
                tool_candidates=["shift_event_time"],
                match_keywords=["偏移活动时间", "修改活动时间", "调整活动时间"],
                param_schema={
                    "event_id": {"type": "integer", "required": True},
                    "event_to_time": {"type": "string", "required": True},
                },
            ),
            SkillMetadata(
                skill_name="send_gifts",
                description="送礼物能力，支持用户向直播间发送指定礼物多次",
                skill_type="execute",
                tool_candidates=["send_gifts_to_one_room"],
                match_keywords=["送礼物", "发送礼物", "刷礼物", "连送礼物"],
                param_schema={
                    "gift_id": {"type": "integer", "required": True},
                    "user_id": {"type": "integer", "required": True},
                    "room_id": {"type": "integer", "required": True},
                    "num": {"type": "integer", "required": True},
                    "count": {"type": "integer", "required": True},
                },
            ),
        ],
        tools=[
            ToolMetadata(
                tool_name="add_gift_to_exclusive_tab",
                description="发放用户/直播间专属 tab 礼物",
                platform="database",
                service="gift",
                executor="database_sql_executor",
                required_params=["gift_id"],
                conditional_required_params=[
                    {"when": "gift_id startswith 2", "required": ["user_id"]},
                    {"when": "gift_id startswith 7", "required": ["room_id"]},
                ],
                metadata={
                    "table_name": "live_custom",
                    "operation": "grant",
                    "sql_type": "insert",
                    "sql_template": "INSERT INTO live_custom (...) VALUES (...)",
                    "business_meaning": "新增 live_custom 记录 = 发放专属礼物",
                },
            ),
            ToolMetadata(
                tool_name="shift_event_time",
                description="调用测试工具后台接口偏移活动时间",
                platform="test_admin_backend",
                service="event",
                executor="http_api_executor",
                required_params=["event_id", "event_to_time"],
                metadata={
                    "method": "POST",
                    "url": "/api/event/shift_time",
                    "auth_provider": "test_admin_backend",
                    "request_mapping": {
                        "event_id": "eventId",
                        "event_to_time": "targetTime",
                    },
                    "response_mapping": {
                        "success_field": "success",
                        "message_field": "message",
                        "data_field": "data",
                    },
                },
            ),
            ToolMetadata(
                tool_name="send_gifts_to_one_room",
                description="使用测试脚本给单个直播间发送指定礼物多次",
                platform="test_script",
                service="gift_script",
                executor="script_executor",
                required_params=["gift_id", "user_id", "room_id", "num", "count"],
                metadata={
                    "script": {
                        "repo": "git@gitlab.xxx.com:test/send-gift-scripts.git",
                        "branch": "master",
                        "path": "gift/send_gifts_to_one_room.py",
                        "sync_before_run": True,
                    },
                    "param_mapping": {
                        "gift_id": "--gift-id",
                        "user_id": "--user-id",
                        "room_id": "--room-id",
                        "num": "--num",
                        "count": "--count",
                    },
                    "auth": {"provider": "script_auth", "type": "auto"},
                    "runtime": {
                        "timeout_seconds": 120,
                        "max_concurrency": 2,
                        "max_output_chars": 8000,
                    },
                },
            ),
        ],
    )
