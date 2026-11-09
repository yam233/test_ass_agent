from agent_core.workflow_audit import audit_action

"""Transactional synthetic platform for the workflow contracts. No network calls."""
import json
from agent_core.action_store import ActionError, canonical, scope
from agent_core.mock_platforms import MockPlatforms
from agent_core.workflow_contracts import WRITES, SPECS, normalize, failure
from agent_core.langgraph_agent.permissions import PermissionGuard
from agent_core.workflow_policy import check_tool, snapshot_hash, check_cleanup_impact


class WorkflowPlatform(MockPlatforms):
    WRITE_TOOLS = WRITES

    def __init__(self, path):
        super().__init__(path)
        with self.actions.connection() as db:
            db.executescript(
                """
            CREATE TABLE IF NOT EXISTS workflow_config (env TEXT, key TEXT, value TEXT, version TEXT, PRIMARY KEY(env,key));
            CREATE TABLE IF NOT EXISTS workflow_preconditions (action_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workflow_changes (action_id TEXT PRIMARY KEY, env TEXT, key TEXT, before_json TEXT, after_json TEXT);
            """
            )

    @staticmethod
    def check_policy(tool, context, saved_policy=None):
        return check_tool(tool, context, saved_policy)

    @staticmethod
    def normalize_write(tool, params):
        return normalize(tool, params)

    def _source(self, name, args, context, db):
        if name not in {"cleanup_data", "rollback_config"}:
            return
        source_id = args["batch_id"] if name == "cleanup_data" else args["change_id"]
        original = self.actions.get(source_id, context, db)
        expected = (
            {"seed_test_data", "run_script"}
            if name == "cleanup_data"
            else {"update_config"}
        )
        if original["tool"] not in expected:
            raise ActionError("BAD_ARGS", "来源动作类型不匹配")
        if not db.execute(
            "SELECT 1 FROM platform_receipts WHERE action_id=?", (source_id,)
        ).fetchone():
            raise ActionError("NOT_FOUND", "来源动作尚未提交")

    def prepare(self, tool, params, context, saved_policy=None):
        args = normalize(tool, params)
        with self.actions.connection() as db:
            self._source(tool, args, context, db)
        policy = self.check_policy(tool, context, saved_policy)
        impact = self.preview(tool, args, context) if tool == "cleanup_data" else None
        if (
            impact is not None
            and impact["affected_quantity"] > policy["cleanup_max_quantity"]
        ):
            raise ActionError("PERMISSION_DENIED", "清理影响量超过服务端阈值")
        with self.actions.connection() as db:
            snapshot = (
                self._config(db, scope(context)[2], args["key"])
                if tool == "update_config"
                else None
            )
        action = self.actions.prepare(tool, args, context, supersede=False)
        if snapshot is not None:
            with self.actions.connection(write=True) as db:
                db.execute(
                    "INSERT OR IGNORE INTO workflow_preconditions VALUES (?,?)",
                    (action["action_id"], canonical(snapshot)),
                )
        if impact is not None:
            saved = {
                "impact": impact,
                "hash": snapshot_hash(action["action_id"], tool, args, impact),
            }
            with self.actions.connection(write=True) as db:
                db.execute(
                    "INSERT OR IGNORE INTO workflow_preconditions VALUES (?,?)",
                    (action["action_id"], canonical(saved)),
                )
                saved = json.loads(
                    db.execute(
                        "SELECT snapshot FROM workflow_preconditions WHERE action_id=?",
                        (action["action_id"],),
                    ).fetchone()[0]
                )
            action["snapshot_hash"] = saved["hash"]
        return action

    def preview(self, tool, args, context):
        args = normalize(tool, args)
        with self.actions.connection() as db:
            self._source(tool, args, context, db)
            if tool == "update_config":
                old = self._config(db, scope(context)[2], args["key"])
                return {"before": old["value"], "after": args["value"]}
            if tool == "cleanup_data":
                row = db.execute(
                    "SELECT payload FROM gifts WHERE id=?", (args["batch_id"],)
                ).fetchone()
                return {
                    "affected_quantity": json.loads(row[0])["quantity"] if row else 0,
                    "batch_id": args["batch_id"],
                }
        return args

    @staticmethod
    def _config(db, env, key):
        row = db.execute(
            "SELECT value,version FROM workflow_config WHERE env=? AND key=?",
            (env, key),
        ).fetchone()
        return {
            "key": key,
            "value": json.loads(row[0])
            if row
            else (1 if key == "gift_multiplier" else False),
            "version": row[1] if row else None,
        }

    def execute(self, tool, params, context=None, saved_policy=None):
        context = context or {}
        try:
            args = normalize(tool, params)
            policy = check_tool(tool, context, saved_policy)
            d = PermissionGuard().evaluate(
                "execute" if tool in WRITES else "query",
                {**context, "tool_name": tool, "execute_confirmed": True},
            )
            if not d.allowed:
                raise ActionError(d.code, d.message)
            if tool in WRITES:
                return self._write(tool, args, context, policy)
            read_fault = {
                "f_403": "PERMISSION_DENIED",
                "f_5xx": "TRANSIENT",
                "f_timeout": "TIMEOUT",
            }.get(context.get("fault_id"))
            if read_fault:
                return failure(read_fault, "可复现的读取故障", tool)
            if tool == "list_scripts":
                return self._ok(
                    tool, {"scripts": [{"id": "send_gifts", "synthetic": True}]}
                )
            if tool == "query_config":
                with self.actions.connection() as db:
                    return self._ok(
                        tool, self._config(db, scope(context)[2], args["key"])
                    )
            if tool == "query_data":
                # Only scoped workflow batches; no cross-user or cross-environment data.
                with self.actions.connection() as db:
                    ids = {
                        r[0]
                        for r in db.execute(
                            "SELECT action_id FROM actions WHERE operator=? AND session_id=? AND env=?",
                            scope(context),
                        )
                    }
                rows = [
                    r
                    for r in self.snapshot(args["table"])
                    if r.get("batch_id") in ids
                    and all(r.get(k) == v for k, v in args.items() if k != "table")
                ]
                return self._ok(
                    tool,
                    {
                        "rows": rows,
                        "row_count": len(rows),
                        "total_quantity": sum(r.get("quantity", 0) for r in rows),
                    },
                )
            return failure("BAD_ARGS", "该工具由工作流运行时处理", tool)
        except ActionError as e:
            return failure(e.code, str(e), tool, "blocked")
        except (ValueError, TypeError) as e:
            return failure("BAD_ARGS", str(e), tool)

    def _write(self, tool, args, context, saved_policy=None):
        if context.get("dry_run"):
            return self._ok(
                tool, {"preview": self.preview(tool, args, context)}, "planned"
            )
        aid = context.get("action_id")
        if not aid:
            return failure("CONFIRM_REQUIRED", "需要绑定 action_id 的审批", tool, "blocked")
        with self.actions.connection(write=True) as db:
            receipt = db.execute(
                "SELECT result_json FROM platform_receipts WHERE action_id=?", (aid,)
            ).fetchone()
            self.actions.validate(
                aid, tool, args, context, db, has_receipt=receipt is not None
            )
            if receipt:
                return json.loads(receipt[0])
            self._source(tool, args, context, db)
            fault = context.get("fault_id")
            if fault in {"f_403", "f_5xx", "f_timeout", "f_bad_type", "f_ambiguous"}:
                code = {
                    "f_403": "PERMISSION_DENIED",
                    "f_5xx": "TRANSIENT",
                    "f_timeout": "TIMEOUT",
                    "f_bad_type": "BAD_ARGS",
                    "f_ambiguous": "AMBIGUOUS",
                }[fault]
                return failure(code, "可复现的模拟故障", tool)
            if fault not in {None, "", "f_halfseed", "f_response_loss"}:
                return failure("BAD_ARGS", "未知故障 ID", tool)
            env = scope(context)[2]
            if tool in {"seed_test_data", "run_script"}:
                actual = (
                    args["quantity"] // 2 if fault == "f_halfseed" else args["quantity"]
                )
                payload = {**args, "quantity": actual, "batch_id": aid, "source": tool}
                db.execute("INSERT INTO gifts VALUES (?,?)", (aid, canonical(payload)))
                if tool == "run_script":
                    db.execute(
                        "INSERT INTO script_runs VALUES (?,?)",
                        (aid, canonical(payload)),
                    )
                stored = json.loads(
                    db.execute(
                        "SELECT payload FROM gifts WHERE id=?", (aid,)
                    ).fetchone()[0]
                )
                data = {
                    "batch_id": aid,
                    "expected": args["quantity"],
                    "actual": stored["quantity"],
                }
                status = (
                    "success"
                    if data["actual"] == data["expected"]
                    else "partial_success"
                )
            elif tool == "cleanup_data":
                row = db.execute(
                    "SELECT payload FROM gifts WHERE id=?", (args["batch_id"],)
                ).fetchone()
                actual = json.loads(row[0])["quantity"] if row else 0
                saved = db.execute(
                    "SELECT snapshot FROM workflow_preconditions WHERE action_id=?",
                    (aid,),
                ).fetchone()
                if (
                    not saved
                    or json.loads(saved[0])["impact"]["affected_quantity"] != actual
                ):
                    return failure("CONFLICT", "清理影响量已改变，请重新预览审批", tool)
                check_cleanup_impact(
                    tool, args, check_tool(tool, context, saved_policy), db
                )
                data = {"batch_id": args["batch_id"], "actual": actual}
                db.execute("DELETE FROM gifts WHERE id=?", (args["batch_id"],))
                status = "success"
            else:
                if tool == "update_config":
                    key, value = args["key"], args["value"]
                    saved = db.execute(
                        "SELECT snapshot FROM workflow_preconditions WHERE action_id=?",
                        (aid,),
                    ).fetchone()
                    if (
                        not saved
                        or json.loads(saved[0])["version"]
                        != self._config(db, env, key)["version"]
                    ):
                        return failure("CONFLICT", "审批预览之后配置已变化，请重新查询并审批", tool)
                else:
                    change = db.execute(
                        "SELECT * FROM workflow_changes WHERE action_id=?",
                        (args["change_id"],),
                    ).fetchone()
                    if not change:
                        return failure("NOT_FOUND", "找不到配置变更", tool)
                    key, value = change["key"], json.loads(change["before_json"])
                    if self._config(db, env, key)["version"] != args["change_id"]:
                        return failure("CONFLICT", "配置已有后续修改，不能覆盖", tool)
                before = self._config(db, env, key)["value"]
                db.execute(
                    "INSERT OR REPLACE INTO workflow_config VALUES (?,?,?,?)",
                    (env, key, canonical(value), aid),
                )
                db.execute(
                    "INSERT INTO workflow_changes VALUES (?,?,?,?,?)",
                    (aid, env, key, canonical(before), canonical(value)),
                )
                after = self._config(db, env, key)["value"]
                data, status = {"key": key, "before": before, "after": after}, "success"
            result = self._ok(tool, {**data, "action_id": aid}, status)
            db.execute(
                "INSERT INTO platform_receipts VALUES (?,?)", (aid, canonical(result))
            )
            audit_action(db, aid, "receipt", context, {"status": result["status"]})
        if context.get("fault_id") == "f_response_loss":
            return failure("OUTCOME_UNKNOWN", "提交后丢失响应；查询回执核验", tool, "unknown")
        return result
