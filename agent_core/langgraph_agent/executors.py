"""Platform executors for metadata-driven tools."""
from pathlib import Path
import importlib
import threading
from typing import Any, Dict, Optional

from agent_core.langgraph_agent.common import ErrorCode, error_result
from agent_core.langgraph_agent.metadata import PlatformMetadataRegistry, ToolMetadata
from agent_core.skills.standard import TestScriptSkill


class ExecutionContext:
    def __init__(self, registry: PlatformMetadataRegistry):
        self.registry = registry


class BasePlatformExecutor:
    name = "base_executor"

    def __init__(self, execution_context: ExecutionContext):
        self.execution_context = execution_context

    def execute(self, tool: ToolMetadata, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _base_data(tool: ToolMetadata) -> Dict[str, Any]:
        return {
            "tool_name": tool.tool_name,
            "platform": tool.platform,
            "service": tool.service,
            "executor": tool.executor,
            "metadata": tool.metadata,
        }


class DatabaseSqlExecutor(BasePlatformExecutor):
    name = "database_sql_executor"

    def execute(self, tool: ToolMetadata, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = context or {}
        data = self._base_data(tool)
        data.update({
            "table_name": tool.metadata.get("table_name"),
            "operation": tool.metadata.get("operation"),
            "sql_type": tool.metadata.get("sql_type"),
            "sql_template": tool.metadata.get("sql_template"),
            "business_meaning": tool.metadata.get("business_meaning"),
            "params": params,
        })

        if context.get("dry_run", True):
            return {
                "success": True,
                "status": "planned",
                "code": ErrorCode.OK.value,
                "message": "已生成数据库平台执行计划，默认 dry_run 未写库",
                "data": data,
                "tool_name": tool.tool_name,
            }

        callable_path = tool.metadata.get("callable")
        if callable_path:
            result = self._call_callable(callable_path, params)
            result.setdefault("data", {})
            if isinstance(result["data"], dict):
                result["data"].update({k: v for k, v in data.items() if k not in result["data"]})
            result.setdefault("tool_name", tool.tool_name)
            return result

        return error_result(
            ErrorCode.TOOL_EXECUTION_ERROR,
            "数据库执行器未配置真实写入 callable",
            data,
            status="blocked",
            request_id=context.get("request_id"),
            tool_name=tool.tool_name,
        )

    @staticmethod
    def _call_callable(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        module_name, func_name = path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        return func(**params)


class HttpApiExecutor(BasePlatformExecutor):
    name = "http_api_executor"

    def execute(self, tool: ToolMetadata, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = context or {}
        request_mapping = tool.metadata.get("request_mapping", {})
        mapped_params = {
            request_mapping.get(key, key): value
            for key, value in params.items()
            if key != "context"
        }
        data = self._base_data(tool)
        data.update({
            "method": tool.metadata.get("method"),
            "url": tool.metadata.get("url"),
            "auth_provider": tool.metadata.get("auth_provider"),
            "request_params": mapped_params,
            "response_mapping": tool.metadata.get("response_mapping", {}),
        })

        if context.get("dry_run", True):
            return {
                "success": True,
                "status": "planned",
                "code": ErrorCode.OK.value,
                "message": "已生成测试工具后台接口调用计划，默认 dry_run 未请求后台",
                "data": data,
                "tool_name": tool.tool_name,
            }

        return error_result(
            ErrorCode.TOOL_EXECUTION_ERROR,
            "HTTP API 执行器未配置真实请求客户端",
            data,
            status="blocked",
            request_id=context.get("request_id"),
            tool_name=tool.tool_name,
        )


class ScriptExecutor(BasePlatformExecutor):
    name = "script_executor"
    _semaphore = threading.BoundedSemaphore(value=2)

    def execute(self, tool: ToolMetadata, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = context or {}
        script_meta = tool.metadata.get("script", {})
        param_mapping = tool.metadata.get("param_mapping", {})
        runtime = tool.metadata.get("runtime", {})
        args = []
        for key, flag in param_mapping.items():
            if params.get(key) not in (None, "", [], {}):
                args.extend([flag, str(params[key])])

        data = self._base_data(tool)
        data.update({
            "script": script_meta,
            "args": args,
            "auth": tool.metadata.get("auth", {}),
            "runtime": runtime,
        })

        if context.get("dry_run", True):
            return {
                "success": True,
                "status": "planned",
                "code": ErrorCode.OK.value,
                "message": "已生成测试脚本执行计划，默认 dry_run 未执行脚本",
                "data": data,
                "tool_name": tool.tool_name,
            }

        if not self._semaphore.acquire(blocking=False):
            return error_result(
                ErrorCode.RESOURCE_BUSY,
                "当前脚本执行任务过多，请稍后重试",
                {"limit": runtime.get("max_concurrency", 2)},
                status="blocked",
                request_id=context.get("request_id"),
                tool_name=tool.tool_name,
            )
        try:
            local_path = context.get("script_repo_path") or script_meta.get("local_path") or "scripts"
            script_path = script_meta.get("path", "")
            if not script_path:
                return error_result(
                    ErrorCode.NEED_MORE_INFO,
                    "脚本元信息缺少 path",
                    data,
                    status="need_more_info",
                    request_id=context.get("request_id"),
                    tool_name=tool.tool_name,
                )
            if not self._is_allowed_script(script_path):
                return error_result(
                    ErrorCode.PERMISSION_DENIED,
                    "脚本路径不在允许目录内",
                    {"script_path": script_path},
                    status="blocked",
                    request_id=context.get("request_id"),
                    tool_name=tool.tool_name,
                )
            skill = TestScriptSkill(local_path, branch=script_meta.get("branch"))
            if script_meta.get("sync_before_run", True) and (Path(local_path) / ".git").exists():
                sync = skill.sync_latest()
                if not sync.get("success"):
                    return sync
            return skill.execute_script(
                script_path,
                args=args,
                approved=True,
                timeout_seconds=int(runtime.get("timeout_seconds", 120)),
                max_output_chars=int(runtime.get("max_output_chars", 8000)),
            )
        finally:
            self._semaphore.release()

    @staticmethod
    def _is_allowed_script(script_path: str) -> bool:
        first_part = Path(script_path).parts[0] if Path(script_path).parts else ""
        return first_part in {"gift", "event", "room"}


class PlatformExecutorRouter:
    def __init__(self, registry: PlatformMetadataRegistry):
        execution_context = ExecutionContext(registry)
        self.executors = {
            "database_sql_executor": DatabaseSqlExecutor(execution_context),
            "http_api_executor": HttpApiExecutor(execution_context),
            "script_executor": ScriptExecutor(execution_context),
        }

    def execute(self, tool: ToolMetadata, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        executor = self.executors.get(tool.executor)
        if not executor:
            return error_result(
                ErrorCode.TOOL_NOT_FOUND,
                f"未找到平台执行器: {tool.executor}",
                {"tool_name": tool.tool_name, "platform": tool.platform},
                status="failed",
                request_id=(context or {}).get("request_id"),
                tool_name=tool.tool_name,
            )
        return executor.execute(tool, params, context)
