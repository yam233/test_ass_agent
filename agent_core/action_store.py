"""Persistent operation snapshots and approvals for the local mock runtime."""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scope(context):
    return (str(context.get("operator") or "local"), str(context.get("session_id") or "default"),
            str(context.get("env") or context.get("environment") or "uat").lower())


class ActionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ActionStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY, operator TEXT NOT NULL, session_id TEXT NOT NULL,
                    env TEXT NOT NULL, tool TEXT NOT NULL, args_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, request_id TEXT, status TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL, approved_at REAL,
                    result_json TEXT,
                    UNIQUE(operator, session_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS platform_receipts (
                    action_id TEXT PRIMARY KEY, result_json TEXT NOT NULL
                );
            ''')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            raise ActionError("ACTION_NOT_FOUND", "找不到动作，请先提交操作")
        value = dict(row)
        value["args"] = json.loads(value.pop("args_json"))
        value["result"] = json.loads(value.pop("result_json") or "null")
        return value

    def get(self, action_id, context, db=None):
        if db is None:
            with self.connection() as connection:
                return self.get(action_id, context, connection)
        value = self.decode(db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone())
        if (value["operator"], value["session_id"], value["env"]) != scope(context):
            raise ActionError("APPROVAL_MISMATCH", "操作人、会话或环境与动作快照不一致")
        return value

    def prepare(self, tool, args, context, supersede=True):
        owner, session, env = scope(context)
        fingerprint = hashlib.sha256(canonical([owner, session, env, tool, args]).encode()).hexdigest()
        request_id = context.get("request_id") or None
        with self.connection(write=True) as db:
            if request_id:
                previous = db.execute("SELECT * FROM actions WHERE operator=? AND session_id=? AND request_id=?", (owner, session, request_id)).fetchone()
                if previous:
                    value = self.decode(previous)
                    if value["fingerprint"] != fingerprint:
                        raise ActionError("REQUEST_CONFLICT", "同一 request_id 不能对应不同动作")
                    return value
            if supersede:
                db.execute("UPDATE actions SET status='superseded' WHERE operator=? AND session_id=? AND env=? AND status='pending'", (owner, session, env))
            action_id, now = str(uuid.uuid4()), time.time()
            db.execute("INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL)",
                       (action_id, owner, session, env, tool, canonical(args), fingerprint, request_id, now, now + 300))
            return self.get(action_id, context, db)

    def latest(self, context, completed=False):
        statuses = ("success", "partial_success") if completed else ("pending",)
        with self.connection() as db:
            placeholders = ",".join("?" for _ in statuses)
            row = db.execute(f"SELECT * FROM actions WHERE operator=? AND session_id=? AND env=? AND status IN ({placeholders}) ORDER BY created_at DESC, rowid DESC LIMIT 1", (*scope(context), *statuses)).fetchone()
            if not completed and row is not None:
                # A delayed unbound 'confirm' must not approve a replacement plan.
                replaced = db.execute("SELECT 1 FROM actions WHERE operator=? AND session_id=? AND env=? AND status='superseded' LIMIT 1", scope(context)).fetchone()
                if replaced:
                    raise ActionError("ACTION_ID_REQUIRED", "该会话曾替换待审批动作，请明确提供 action_id")
            return self.decode(row)

    def approve(self, action_id, context):
        with self.connection(write=True) as db:
            value = self.get(action_id, context, db)
            if value["status"] not in {"pending", "approved", "running", "retryable", "unknown", "success", "partial_success"}:
                raise ActionError("APPROVAL_INVALID", "动作已取消、被替换或失败，请重新提交")
            if value["status"] not in {"success", "partial_success"} and value["expires_at"] < time.time():
                raise ActionError("APPROVAL_EXPIRED", "审批已过期，请重新提交动作")
            if value['tool']=='cleanup_data' and value['status']=='pending':
                saved=db.execute('SELECT snapshot FROM workflow_preconditions WHERE action_id=?',(action_id,)).fetchone()
                if not saved or context.get('confirm_effect')!='delete_batch' or context.get('snapshot_hash')!=json.loads(saved[0])['hash']:
                    raise ActionError('CONFIRM_REQUIRED','清理需明确确认删除影响快照')
            if value["status"] == "pending":
                db.execute("UPDATE actions SET status='approved', approved_at=? WHERE action_id=?", (time.time(), action_id))
            return self.get(action_id, context, db)

    def deny(self, action_id, context):
        with self.connection(write=True) as db:
            value = self.get(action_id, context, db)
            if value["status"] not in {"pending", "approved", "denied"}:
                raise ActionError("APPROVAL_INVALID", "该动作已开始或结束，不能取消为未执行")
            db.execute("UPDATE actions SET status='denied' WHERE action_id=?", (action_id,))

    def validate(self, action_id, tool, args, context, db, has_receipt=False):
        value = self.get(action_id, context, db)
        if value["tool"] != tool or canonical(value["args"]) != canonical(args):
            raise ActionError("APPROVAL_MISMATCH", "工具或参数与审批快照不一致，请重新提交")
        if value["status"] not in {"approved", "running", "retryable", "unknown", "success", "partial_success"}:
            raise ActionError("APPROVAL_INVALID", "动作尚未审批或审批已失效")
        if not has_receipt and value["expires_at"] < time.time():
            raise ActionError("APPROVAL_EXPIRED", "审批已过期，请重新提交")
        if not has_receipt and value["status"] in {"success", "partial_success"}:
            raise ActionError("STATE_INCONSISTENT", "已完成动作缺少平台回执，停止执行")
        return value

    def running(self, action_id, context):
        with self.connection(write=True) as db:
            value = self.get(action_id, context, db)
            if value["status"] not in {"approved", "running", "retryable", "unknown"}:
                raise ActionError("APPROVAL_INVALID", "该动作不可执行或重试")
            if value["expires_at"] < time.time():
                raise ActionError("APPROVAL_EXPIRED", "审批已过期，请重新提交")
            db.execute("UPDATE actions SET status='running' WHERE action_id=?", (action_id,))

    def complete(self, action_id, result):
        with self.connection(write=True) as db:
            # Commit and receipt are atomic. Even if the successful worker died
            # before updating this ledger, its receipt outranks a late failure.
            receipt = db.execute("SELECT result_json FROM platform_receipts WHERE action_id=?", (action_id,)).fetchone()
            if receipt is not None:
                result = json.loads(receipt["result_json"])
            status = result["status"]
            if result.get("code") in {"TIMEOUT", "TRANSIENT"}:
                status = "retryable"
            elif result.get("code") == "OUTCOME_UNKNOWN":
                status = "unknown"
            db.execute("UPDATE actions SET status=?, result_json=? WHERE action_id=? AND status NOT IN ('success','partial_success','denied','superseded')", (status, canonical(result), action_id))

    def list_actions(self):
        with self.connection() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM actions ORDER BY created_at, rowid")]
