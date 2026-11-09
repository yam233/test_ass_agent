"""LangChain-style tools for database, backend, and script skills."""
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agent_core.langgraph_agent.compat import BaseTool
from agent_core.langgraph_agent.common import ErrorCode, error_result, format_result
from agent_core.langgraph_agent.executors import PlatformExecutorRouter
from agent_core.langgraph_agent.metadata import PlatformMetadataRegistry, ToolMetadata, default_metadata_registry
from agent_core.langgraph_agent.permissions import PermissionGuard
from agent_core.skills.standard import (
    BackendMetadataSkill,
    DatabaseExportSkill,
    DatabaseQuerySkill,
    DatabaseWriteSkill,
    TestScriptSkill,
)


class DBQueryInput(BaseModel):
    sql: str = Field(default="")
    query: Dict[str, Any] = Field(default_factory=dict)
    dialect: str = Field(default="mysql")


class MetadataDrivenTool(BaseTool):
    """Tool wrapper that dispatches through platform metadata and executors."""

    def __init__(
        self,
        tool_metadata: ToolMetadata,
        executor_router: PlatformExecutorRouter,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.tool_metadata = tool_metadata
        self.executor_router = executor_router
        self.name = tool_metadata.tool_name
        self.description = tool_metadata.description

    def _run(self, context: Optional[Dict[str, Any]] = None, **params: Any) -> Dict[str, Any]:
        context = context or {}
        missing = self.tool_metadata.missing_params(params)
        if missing:
            return error_result(
                ErrorCode.NEED_MORE_INFO,
                f"缺少必要参数: {', '.join(missing)}",
                {"missing_params": missing},
                status="need_more_info",
                request_id=context.get("request_id"),
                tool_name=self.name,
            )
        return self.executor_router.execute(self.tool_metadata, params, context)


class DBQueryTool(BaseTool):
    name: str = "db_query"
    description: str = "只读数据库查询工具，支持 SQL SELECT/SHOW/DESCRIBE/EXPLAIN 和安全 Mongo 查询。"

    def _run(self, sql: str = "", query: Optional[Dict[str, Any]] = None, dialect: str = "mysql", **kwargs: Any) -> Dict[str, Any]:
        if dialect == "mongo":
            ok, reason = DatabaseQuerySkill.validate_mongo_query(query or {})
        else:
            ok, reason = DatabaseQuerySkill.validate_sql(sql)
        if not ok:
            return {"success": False, "status": "blocked", "message": reason, "data": {}}
        return {
            "success": False,
            "status": "blocked",
            "message": "数据库连接未在 LangGraph 工具层配置；已完成只读合法性校验",
            "data": {"validated": True, "dialect": dialect},
        }


class DBWriteTool(BaseTool):
    name: str = "db_write"
    description: str = "数据库增删改工具，执行前需要审批，并预留备份/回滚钩子。"

    def __init__(self, write_skill: Optional[DatabaseWriteSkill] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.write_skill = write_skill or DatabaseWriteSkill()
        self.guard = PermissionGuard()

    def _run(self, params: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        decision = self.guard.evaluate("write", context or {})
        if not decision.allowed or decision.need_confirm:
            return {"success": False, "status": "blocked", "message": decision.message, "data": {"need_confirm": decision.need_confirm}}
        return format_result(self.write_skill.execute(params or {}, approved=True), self.name)


class DBExportTool(BaseTool):
    name: str = "db_export"
    description: str = "将查询结果导出到 CSV 文件。"

    def _run(self, rows: Optional[List[Dict[str, Any]]] = None, output_path: str = "exports/query_result.csv", fields: Optional[List[str]] = None, **kwargs: Any) -> Dict[str, Any]:
        return DatabaseExportSkill.export_csv(rows or [], output_path, fields)


class BackendFeatureTool(BaseTool):
    name: str = "backend_feature"
    description: str = "查询测试后台功能入口、页面路径和业务说明。"

    def __init__(self, entries: Optional[List[Dict[str, Any]]] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.skill = BackendMetadataSkill(entries or self._load_entries())

    def _run(self, keyword: str = "", **kwargs: Any) -> Dict[str, Any]:
        return self.skill.search(keyword)

    @staticmethod
    def _load_entries() -> List[Dict[str, Any]]:
        try:
            from agent_plugins.ear_test.backend_metadata import BackendUrlLoader
        except Exception:
            return []
        try:
            return BackendUrlLoader().load_entries()
        except Exception:
            return []


class ScriptScanTool(BaseTool):
    name: str = "script_scan"
    description: str = "扫描测试脚本仓库并返回脚本列表。"

    def __init__(self, repo_path: str = "scripts", **kwargs: Any):
        super().__init__(**kwargs)
        self.script_skill = TestScriptSkill(repo_path)

    def _run(self, **kwargs: Any) -> Dict[str, Any]:
        return self.script_skill.scan_scripts()


class ScriptReadTool(BaseTool):
    name: str = "script_read"
    description: str = "读取测试脚本源码内容。"

    def __init__(self, repo_path: str = "scripts", **kwargs: Any):
        super().__init__(**kwargs)
        self.script_skill = TestScriptSkill(repo_path)

    def _run(self, script_path: str = "", **kwargs: Any) -> Dict[str, Any]:
        if not script_path:
            return {"success": False, "status": "need_more_info", "message": "请补充脚本路径", "data": {"missing_params": ["script_path"]}}
        return self.script_skill.read_script(script_path)


class ScriptRunTool(BaseTool):
    name: str = "script_run"
    description: str = "同步最新代码后执行测试脚本，执行前必须管理员确认。"
    _semaphore = threading.BoundedSemaphore(value=2)

    def __init__(self, repo_path: str = "scripts", **kwargs: Any):
        super().__init__(**kwargs)
        self.script_skill = TestScriptSkill(repo_path)
        self.guard = PermissionGuard()

    def _run(
        self,
        script_path: str = "",
        args: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        context = context or {}
        context = {**context, "tool_name": self.name}
        decision = self.guard.evaluate("script_execute", context)
        if not decision.allowed or decision.need_confirm:
            return error_result(
                decision.code,
                decision.message,
                {"need_confirm": decision.need_confirm},
                status="blocked",
                request_id=context.get("request_id"),
                tool_name=self.name,
            )
        if not script_path:
            return error_result(
                ErrorCode.NEED_MORE_INFO,
                "请补充脚本路径",
                {"missing_params": ["script_path"]},
                status="need_more_info",
                request_id=context.get("request_id"),
                tool_name=self.name,
            )
        if not self._semaphore.acquire(blocking=False):
            return error_result(
                ErrorCode.RESOURCE_BUSY,
                "当前脚本执行任务过多，请稍后重试",
                {"limit": 2},
                status="blocked",
                request_id=context.get("request_id"),
                tool_name=self.name,
            )
        try:
            if (Path(self.script_skill.repo_path) / ".git").exists():
                sync_result = self.script_skill.sync_latest()
                if not sync_result.get("success"):
                    return sync_result
            timeout_seconds = int(context.get("script_timeout_seconds") or 120)
            max_output_chars = int(context.get("script_max_output_chars") or 8000)
            return self.script_skill.execute_script(
                script_path,
                args=args or [],
                approved=True,
                timeout_seconds=timeout_seconds,
                max_output_chars=max_output_chars,
            )
        finally:
            self._semaphore.release()


def metadata_tools(registry: Optional[PlatformMetadataRegistry] = None) -> Dict[str, BaseTool]:
    registry = registry or default_metadata_registry()
    router = PlatformExecutorRouter(registry)
    return {
        tool.tool_name: MetadataDrivenTool(tool_metadata=tool, executor_router=router)
        for tool in registry.platform_tools()
    }


def default_tools(repo_path: str = "scripts", registry: Optional[PlatformMetadataRegistry] = None) -> Dict[str, BaseTool]:
    tools = [
        DBQueryTool(),
        DBWriteTool(),
        DBExportTool(),
        BackendFeatureTool(),
        ScriptScanTool(repo_path=repo_path),
        ScriptReadTool(repo_path=repo_path),
        ScriptRunTool(repo_path=repo_path),
    ]
    result = {tool.name: tool for tool in tools}
    result.update(metadata_tools(registry))
    return result
