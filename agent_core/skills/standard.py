"""Standard skill families for DB, backend, and test script capabilities."""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import csv
import sys
import subprocess


class SkillFamily(str, Enum):
    DATABASE_QUERY = "database_query"
    DATABASE_WRITE = "database_write"
    DATABASE_EXPORT = "database_export"
    DATABASE_METADATA = "database_metadata"
    BACKEND_GIFT_ISSUE = "backend_gift_issue"
    BACKEND_QUERY = "backend_query"
    BACKEND_METADATA = "backend_metadata"
    TEST_SCRIPT = "test_script"


@dataclass
class StandardSkillSpec:
    name: str
    family: SkillFamily
    skill_type: str
    description: str = ""
    required_params: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def missing_params(self, params: Dict[str, Any]) -> List[str]:
        return [
            item for item in self.required_params
            if params.get(item) in (None, "", [], {})
        ]


class DatabaseQuerySkill:
    """Read-only MySQL/Mongo query skill facade."""

    READONLY_SQL_PREFIXES = ("select", "show", "describe", "explain")
    BLOCKED_SQL_TOKENS = (" insert ", " update ", " delete ", " drop ", " alter ", " truncate ")

    @classmethod
    def validate_sql(cls, sql: str) -> tuple[bool, str]:
        normalized = f" {sql.strip().lower()} "
        if not normalized.strip().startswith(cls.READONLY_SQL_PREFIXES):
            return False, "数据库查询 Skill 仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN"
        if any(token in normalized for token in cls.BLOCKED_SQL_TOKENS):
            return False, "查询语句包含写操作关键字"
        return True, "ok"

    @staticmethod
    def validate_mongo_query(query: Dict[str, Any]) -> tuple[bool, str]:
        blocked = {"$where", "$function", "$accumulator"}
        if any(key in query for key in blocked):
            return False, "Mongo 查询包含高风险表达式"
        return True, "ok"


class DatabaseWriteSkill:
    """Write skill facade with approval, backup, and rollback hooks."""

    def __init__(
        self,
        backup_snapshot: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        apply_change: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        rollback_change: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.backup_snapshot = backup_snapshot
        self.apply_change = apply_change
        self.rollback_change = rollback_change

    def execute(self, params: Dict[str, Any], approved: bool = False) -> Dict[str, Any]:
        if not approved:
            return {
                "success": False,
                "status": "blocked",
                "message": "数据库写操作需要审批确认",
                "data": {"need_confirm": True}
            }
        snapshot = self.backup_snapshot(params) if self.backup_snapshot else {}
        result = self.apply_change(params) if self.apply_change else {
            "success": False,
            "message": "未配置数据库写操作执行器"
        }
        if isinstance(result, dict):
            result.setdefault("data", {})
            result["data"]["backup_snapshot"] = snapshot
        return result

    def rollback(self, params: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if not self.rollback_change:
            return {"success": False, "message": "未配置回滚执行器"}
        return self.rollback_change(params, snapshot)


class DatabaseExportSkill:
    """Export query results into a local file."""

    @staticmethod
    def export_csv(rows: List[Dict[str, Any]], output_path: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not fields and rows:
            fields = list(rows[0].keys())
        fields = fields or []
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field) for field in fields})
        return {"success": True, "message": f"导出成功: {path}", "data": {"path": str(path), "count": len(rows)}}


class DatabaseMetadataSkill:
    """Pure metadata retrieval; never touches live data."""

    def __init__(self, metadata: Optional[Dict[str, Any]] = None):
        self.metadata = metadata or {}

    def search(self, keyword: str) -> Dict[str, Any]:
        keyword = (keyword or "").lower()
        items = []
        for item in self.metadata.get("items", []):
            haystack = " ".join(str(v) for v in item.values()).lower()
            if keyword in haystack:
                items.append(item)
        return {"success": True, "message": f"找到 {len(items)} 条元信息", "data": {"items": items}}


class BackendGiftIssueSkill:
    """Unified facade for gift issue flows."""

    @classmethod
    def validate(cls, params: Dict[str, Any]) -> tuple[bool, str]:
        if not cls._has_gift(params):
            return False, "缺少礼物参数: gift_id/gift_ids/gift_nums"
        if not cls._has_target(params):
            return False, "缺少发放目标参数: user_id/target_id/room_id/user_ids/room_ids"
        return True, "ok"

    @classmethod
    def normalize(cls, params: Dict[str, Any], location: str) -> Dict[str, Any]:
        normalized = dict(params)
        normalized["issue_location"] = location
        gift_id = normalized.get("gift_id")
        if gift_id:
            normalized.setdefault("gift_type", cls.infer_gift_type(gift_id))
        normalized.setdefault("num", normalized.get("batch_count") or 1)
        if "target_id" in normalized and "user_id" not in normalized and "room_id" not in normalized:
            if normalized.get("issue_type") == "room":
                normalized["room_id"] = normalized["target_id"]
            else:
                normalized["user_id"] = normalized["target_id"]
        return normalized

    @staticmethod
    def infer_gift_type(gift_id: Any) -> str:
        prefix = str(gift_id)[0] if gift_id is not None else ""
        return {
            "2": "user_exclusive",
            "3": "free_backpack",
            "4": "giveaway_backpack",
            "7": "room_exclusive",
            "8": "random_gift",
        }.get(prefix, "unknown")

    @staticmethod
    def _has_target(params: Dict[str, Any]) -> bool:
        return any(
            params.get(name) not in (None, "", [], {})
            for name in ("user_id", "target_id", "room_id", "user_ids", "room_ids")
        )

    @staticmethod
    def _has_gift(params: Dict[str, Any]) -> bool:
        return any(
            params.get(name) not in (None, "", [], {})
            for name in ("gift_id", "gift_ids", "gift_nums")
        )


class BackendQuerySkill:
    """Read-only backend status or record query facade."""

    skill_type = "query"


class BackendMetadataSkill:
    """Backend URL and page-path metadata search."""

    def __init__(self, entries: Optional[List[Dict[str, Any]]] = None):
        self.entries = entries or []

    def search(self, keyword: str) -> Dict[str, Any]:
        keyword = (keyword or "").lower()
        results = [
            item for item in self.entries
            if keyword in " ".join(str(v) for v in item.values()).lower()
        ]
        return {"success": True, "message": f"找到 {len(results)} 个后台入口", "data": {"features": results}}


class TestScriptSkill:
    """Git-backed test script query/execution facade."""

    __test__ = False

    def __init__(self, repo_path: str, branch: Optional[str] = None):
        self.repo_path = Path(repo_path)
        self.branch = branch

    def sync_latest(self) -> Dict[str, Any]:
        if not (self.repo_path / ".git").exists():
            return {"success": False, "message": "脚本仓库不存在或不是 git 仓库"}
        cmd = ["git", "-C", str(self.repo_path), "pull"]
        if self.branch:
            cmd.extend(["origin", self.branch])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return {
            "success": result.returncode == 0,
            "message": result.stdout.strip() or result.stderr.strip(),
            "data": {"returncode": result.returncode}
        }

    def scan_scripts(self) -> Dict[str, Any]:
        scripts = []
        for path in self.repo_path.rglob("*.py"):
            if ".git" in path.parts:
                continue
            scripts.append({"name": path.name, "path": str(path), "relative_path": str(path.relative_to(self.repo_path))})
        return {"success": True, "message": f"扫描到 {len(scripts)} 个脚本", "data": {"scripts": scripts}}

    def read_script(self, relative_path: str) -> Dict[str, Any]:
        path = (self.repo_path / relative_path).resolve()
        if not str(path).startswith(str(self.repo_path.resolve())):
            return {"success": False, "message": "脚本路径非法"}
        if not path.exists():
            return {"success": False, "message": "脚本不存在"}
        return {"success": True, "message": "读取成功", "data": {"path": str(path), "content": path.read_text(encoding="utf-8")}}

    def execute_script(
        self,
        relative_path: str,
        args: Optional[List[str]] = None,
        approved: bool = False,
        timeout_seconds: int = 120,
        max_output_chars: int = 8000,
    ) -> Dict[str, Any]:
        if not approved:
            return {"success": False, "status": "blocked", "message": "脚本执行需要管理员确认", "data": {"need_confirm": True}}
        path = (self.repo_path / relative_path).resolve()
        if not str(path).startswith(str(self.repo_path.resolve())) or not path.exists():
            return {"success": False, "message": "脚本路径非法或不存在"}
        try:
            result = subprocess.run(
                [sys.executable, str(path), *(args or [])],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "status": "timeout",
                "code": "TIMEOUT",
                "message": f"脚本执行超时: {timeout_seconds}s",
                "data": {
                    "stdout": (exc.stdout or "")[:max_output_chars],
                    "stderr": (exc.stderr or "")[:max_output_chars],
                },
            }
        return {
            "success": result.returncode == 0,
            "message": "脚本执行完成" if result.returncode == 0 else "脚本执行失败",
            "data": {
                "returncode": result.returncode,
                "stdout": result.stdout[:max_output_chars],
                "stderr": result.stderr[:max_output_chars],
            }
        }
