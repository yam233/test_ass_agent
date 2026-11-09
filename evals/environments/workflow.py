import json
import sqlite3
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget


class WorkflowEnvironment:
    def __init__(self, path, model=None):
        self.path = path
        self.model = model
        self.reset(0)

    def reset(self, seed):
        self.seed = seed
        self.runtime = WorkflowRuntime(self.path, model=self.model, retry_delays=(0, 0))
        self.runtime.platform.reset()

    async def apply(self, action):
        context = action["context"]
        if action["op"] == "start":
            return await self.runtime.start(
                action["text"], context, Budget(**action.get("budget", {}))
            )
        if action["op"] == "resume":
            return await self.runtime.resume(
                action["task_id"],
                context,
                **{
                    k: v
                    for k, v in action.items()
                    if k not in {"op", "task_id", "context"}
                }
            )
        raise ValueError("unsupported environment operation")

    def snapshot(self):
        with sqlite3.connect(self.path) as db:
            gifts = [json.loads(r[0]) for r in db.execute("SELECT payload FROM gifts")]
            configs = {
                r[0]: json.loads(r[1])
                for r in db.execute("SELECT key,value FROM workflow_config")
            }
            receipts = [
                r[0] for r in db.execute("SELECT action_id FROM platform_receipts")
            ]
            actions = [
                dict(zip(["id", "status", "tool"], r))
                for r in db.execute("SELECT action_id,status,tool FROM actions")
            ]
        return {
            "gifts": gifts,
            "quantity": sum(r["quantity"] for r in gifts),
            "configs": configs,
            "receipts": receipts,
            "actions": actions,
        }

    def invariants(self):
        snapshot = self.snapshot()
        ids = {a["id"] for a in snapshot["actions"]}
        return [
            {"name": "receipt_has_action", "passed": set(snapshot["receipts"]) <= ids},
            {
                "name": "batch_has_receipt",
                "passed": all(
                    r["batch_id"] in snapshot["receipts"] for r in snapshot["gifts"]
                ),
            },
        ]
