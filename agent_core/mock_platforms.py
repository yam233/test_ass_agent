from agent_core.workflow_audit import audit_action

"""Local, synthetic substitutes for the unavailable platforms. Never uses a network."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_core.action_store import ActionError, ActionStore, canonical
from agent_core.langgraph_agent.common import error_result
from agent_core.langgraph_agent.permissions import PermissionGuard


class GiftParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    gift_id: int = Field(gt=0)
    user_id: int | None = Field(default=None, gt=0)
    room_id: int | None = Field(default=None, gt=0)
    quantity: int = Field(default=1, ge=1, le=10000)
    duration_days: int = Field(default=7, ge=1, le=36500)


class ScriptParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    gift_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    room_id: int = Field(gt=0)
    num: int = Field(ge=1, le=1000)
    count: int = Field(ge=1, le=1000)


class EventParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: int = Field(gt=0)
    event_to_time: str = Field(min_length=1, max_length=100)


class QueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: int | None = Field(default=None, gt=0)
    event_id: int | None = Field(default=None, gt=0)
    batch_id: str | None = None


class MockPlatforms:
    READ_TOOLS = {
        "query_gift_records": "gifts",
        "query_event": "events",
        "query_script_runs": "script_runs",
    }
    WRITE_TOOLS = {
        "add_gift_to_exclusive_tab",
        "add_gift_to_backpack",
        "shift_event_time",
        "send_gifts_to_one_room",
    }
    SCRIPT_PATH = "gift/send_gifts_to_one_room.py"

    def __init__(self, path=".mock_state/platforms.sqlite"):
        self.path = str(path)
        self.actions = ActionStore(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS gifts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS script_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS platform_receipts (action_id TEXT PRIMARY KEY, result_json TEXT NOT NULL);
            """
            )

    def snapshot(self, table):
        if table not in {"gifts", "events", "script_runs"}:
            raise ValueError("Unknown mock table")
        with closing(sqlite3.connect(self.path)) as db:
            return [
                json.loads(row[0])
                for row in db.execute(f"SELECT payload FROM {table} ORDER BY rowid")
            ]

    def reset(self, dry_run=False):
        """Exclusive explicit reset; never races an executing workflow."""
        from agent_core.workflow_locks import maintenance_lock

        with maintenance_lock(self.path, exclusive=True), self.actions.connection(
            write=True
        ) as db:
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            names = [
                "gifts",
                "events",
                "script_runs",
                "platform_receipts",
                "actions",
                "workflow_tasks",
                "workflow_refs",
                "workflow_config",
                "workflow_changes",
                "workflow_preconditions",
                "workflow_control",
                "workflow_artifacts",
                "workflow_audit",
                "workflow_jobs",
                "workflow_memory",
            ]
            counts = {
                t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in names
                if t in tables
            }
            if not dry_run:
                if (
                    "workflow_jobs" in tables
                    and db.execute(
                        "SELECT 1 FROM workflow_jobs WHERE status='running' LIMIT 1"
                    ).fetchone()
                ):
                    raise ActionError("RESOURCE_BUSY", "存在执行中的调度任务，不能重置")
                if db.execute(
                    "SELECT 1 FROM actions WHERE status IN ('running','unknown') LIMIT 1"
                ).fetchone():
                    raise ActionError("RESOURCE_BUSY", "存在未对账动作，不能重置")
                for table in counts:
                    db.execute(f"DELETE FROM {table}")
            return {"dry_run": dry_run, "tables": counts}

    @staticmethod
    def normalize_write(tool, params):
        if tool == "shift_event_time":
            value = EventParams(**params).model_dump()
            if not value["event_to_time"].strip():
                raise ValueError("event_to_time 不能为空")
            return value
        if tool == "send_gifts_to_one_room":
            value = ScriptParams(**params).model_dump()
            if value["num"] * value["count"] > 10000:
                raise ValueError("单次模拟送礼上限 10000")
            return value
        if tool not in {"add_gift_to_backpack", "add_gift_to_exclusive_tab"}:
            raise ValueError("未知写工具")
        value = GiftParams(**params).model_dump(exclude_none=True)
        if not value.get("user_id") and not value.get("room_id"):
            raise ValueError("需要 user_id 或 room_id")
        if tool == "add_gift_to_backpack" and (
            not value.get("user_id") or "quantity" not in params
        ):
            raise ValueError("背包礼物需要 user_id 和 quantity")
        if tool == "add_gift_to_exclusive_tab":
            required = (
                "user_id"
                if str(value["gift_id"]).startswith("2")
                else "room_id"
                if str(value["gift_id"]).startswith("7")
                else None
            )
            if required and not value.get(required):
                raise ValueError(f"需要 {required}")
        return value

    def prepare(self, tool, params, context):
        self.check_policy(tool, context)
        return self.actions.prepare(tool, self.normalize_write(tool, params), context)

    @staticmethod
    def check_policy(tool, context):
        from agent_core.workflow_policy import require_write_context

        require_write_context(context)
        # Boolean flags are only used to evaluate policy, never as write authority.
        decision = PermissionGuard().evaluate(
            "execute", {**context, "tool_name": tool, "execute_confirmed": True}
        )
        if not decision.allowed:
            raise ActionError(decision.code, decision.message)

    def receipt(self, action_id, context):
        with self.actions.connection() as db:
            action = self.actions.get(action_id, context, db)
            self.check_policy(action["tool"], context)
            row = db.execute(
                "SELECT result_json FROM platform_receipts WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if row is None:
                return None
            self.actions.validate(
                action_id, action["tool"], action["args"], context, db, has_receipt=True
            )
            return json.loads(row[0])

    def execute(self, tool, params, context=None):
        context = context or {}
        known = (
            self.WRITE_TOOLS
            | self.READ_TOOLS.keys()
            | {"script_scan", "script_read", "script_run", "backend_feature"}
        )
        if tool not in known:
            return self._error("TOOL_NOT_FOUND", "该能力尚未实现 mock", tool)
        try:
            if tool in self.WRITE_TOOLS:
                return self._execute_write(tool, params, context)
            action = "execute" if tool == "script_run" else "query"
            decision = PermissionGuard().evaluate(
                action, {**context, "tool_name": tool}
            )
            if not decision.allowed or decision.need_confirm:
                return self._error(
                    decision.code,
                    decision.message,
                    tool,
                    {"need_confirm": decision.need_confirm},
                    "blocked",
                )
            if tool in self.READ_TOOLS:
                query = QueryParams(**params).model_dump(exclude_none=True)
                rows = [
                    r
                    for r in self.snapshot(self.READ_TOOLS[tool])
                    if all(r.get(k) == v for k, v in query.items())
                ]
                return self._ok(tool, {"rows": rows, "row_count": len(rows)})
            if tool == "script_scan":
                return self._ok(
                    tool,
                    {"scripts": [{"path": self.SCRIPT_PATH, "description": "模拟送礼脚本"}]},
                )
            if tool in {"script_read", "script_run"}:
                if params.get("script_path") != self.SCRIPT_PATH:
                    return self._error("NOT_FOUND", "仅支持内置模拟脚本", tool)
                if tool == "script_read":
                    return self._ok(
                        tool,
                        {
                            "source": "# synthetic fixture: send_gifts(gift_id, user_id, room_id, num, count)"
                        },
                    )
                return self._error(
                    "BAD_ARGS", "请使用送礼工具提供 gift_id、user_id、room_id、num、count", tool
                )
            return self._ok(
                tool,
                {
                    "features": [
                        {"title": "离线测试后台", "description": "支持活动时间查询/调整；无真实后台链接"}
                    ]
                },
            )
        except ActionError as exc:
            return self._error(exc.code, str(exc), tool, status="blocked")
        except (ValidationError, ValueError, TypeError) as exc:
            return self._error("BAD_ARGS", str(exc), tool)

    def _execute_write(self, tool, params, context):
        self.check_policy(tool, context)
        value = self.normalize_write(tool, params)
        if context.get("dry_run"):
            return self._ok(tool, {"plan": value}, status="planned")
        action_id = context.get("action_id")
        if not action_id:
            return self._error(
                "CONFIRM_REQUIRED", "写操作需要已审批的 action_id", tool, status="blocked"
            )
        fault = context.get("fault_id")
        with self.actions.connection(write=True) as db:
            row = db.execute(
                "SELECT result_json FROM platform_receipts WHERE action_id=?",
                (action_id,),
            ).fetchone()
            self.actions.validate(
                action_id, tool, value, context, db, has_receipt=row is not None
            )
            if row is not None:
                result = json.loads(row[0])
                result["data"]["replayed"] = True
                return result
            failures = {
                "f_403": ("PERMISSION_DENIED", "模拟平台拒绝访问"),
                "f_5xx": ("TRANSIENT", "模拟平台 500"),
                "f_timeout": ("TIMEOUT", "模拟请求超时（写入前）"),
            }
            if fault in failures:
                return self._error(*failures[fault], tool, {"action_id": action_id})
            if fault not in (None, "", "f_halfseed", "f_response_loss"):
                return self._error(
                    "BAD_ARGS", "未知 fault_id", tool, {"action_id": action_id}
                )
            payload = dict(value)
            if tool == "shift_event_time":
                table, key, expected = "events", str(value["event_id"]), 1
            else:
                table, key = "gifts", action_id
                expected = (
                    value["num"] * value["count"]
                    if tool == "send_gifts_to_one_room"
                    else value["quantity"]
                )
                payload.update(
                    quantity=expected // 2 if fault == "f_halfseed" else expected,
                    batch_id=action_id,
                    source=tool,
                )
            db.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?, ?)",
                (key, canonical(payload)),
            )
            if tool == "send_gifts_to_one_room":
                db.execute(
                    "INSERT INTO script_runs VALUES (?, ?)",
                    (
                        action_id,
                        canonical(
                            {
                                **payload,
                                "script_path": self.SCRIPT_PATH,
                                "status": "partial_success"
                                if payload["quantity"] != expected
                                else "success",
                            }
                        ),
                    ),
                )
            stored = json.loads(
                db.execute(
                    f"SELECT payload FROM {table} WHERE id=?", (key,)
                ).fetchone()[0]
            )
            actual = stored["quantity"] if table == "gifts" else int(stored == value)
            result = self._ok(
                tool,
                {
                    "expected": expected,
                    "actual": actual,
                    "record": stored,
                    "action_id": action_id,
                    "batch_id": action_id,
                },
                status="success" if actual == expected else "partial_success",
            )
            # Side effect and its receipt share one atomic platform transaction.
            db.execute(
                "INSERT INTO platform_receipts VALUES (?, ?)",
                (action_id, canonical(result)),
            )
            audit_action(
                db, action_id, "receipt", context, {"status": result["status"]}
            )
        if fault == "f_response_loss":
            return self._error(
                "OUTCOME_UNKNOWN",
                "平台响应丢失，结果待核验；请按 action_id 重试",
                tool,
                {"action_id": action_id},
                "unknown",
            )
        return result

    @staticmethod
    def _ok(tool, data, status="success"):
        success = status in {"success", "planned"}
        return {
            "success": success,
            "status": status,
            "code": "OK" if success else "PARTIAL_SUCCESS",
            "message": "模拟操作完成"
            if success
            else f"部分成功 {data['actual']}/{data['expected']}",
            "tool_name": tool,
            "data": {**data, "runtime_mode": "mock"},
        }

    @staticmethod
    def _error(code, message, tool, data=None, status="failed"):
        return error_result(
            code,
            message,
            {**(data or {}), "runtime_mode": "mock"},
            status=status,
            tool_name=tool,
        )
