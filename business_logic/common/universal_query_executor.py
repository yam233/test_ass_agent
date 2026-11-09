"""
通用查询执行器（基于 business_schema）
"""
from typing import Any, Dict, Callable
import logging

from agent_core.skills.standard import DatabaseMetadataSkill
from utils.config_loader import ConfigLoader


logger = logging.getLogger(__name__)


class UniversalQueryExecutor:
    """根据业务元数据将结构化查询路由到本地工具。"""

    def __init__(self, business_code: str = "testops"):
        self.business_code = business_code
        try:
            self.schema = ConfigLoader.load_business_config(business_code, "business_schema.json")
        except Exception as e:
            logger.warning(f"加载 business_schema 失败: {e}")
            self.schema = {}

    def execute(self, query: Dict[str, Any], handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> Dict[str, Any]:
        entity = str(query.get("entity", "")).strip()
        action = str(query.get("action", "query")).strip().lower()
        filters = query.get("filters", {}) or {}
        limit = query.get("limit")
        source = query.get("source")

        entity_key = self._resolve_entity_key(entity)
        if not entity_key:
            return {"success": False, "message": f"❌ 不支持的实体: {entity}", "data": {"entity": entity}}

        if action in {"metadata", "meta", "describe"}:
            return self._query_metadata(entity_key, entity)

        if action not in set(self.schema.get("supported_actions", ["query", "list", "stats"])):
            return {
                "success": False,
                "message": f"❌ 通用查询仅支持只读动作 query/list/stats/metadata，不支持: {action}",
                "data": {"entity": entity_key, "action": action}
            }

        op_cfg = (
            self.schema.get("operation_mappings", {})
            .get(entity_key, {})
            .get(action, {})
        )
        tool_name = op_cfg.get("tool")
        if not tool_name:
            return {
                "success": False,
                "message": f"❌ 实体 {entity} 暂不支持操作 {action}",
                "data": {"entity": entity, "action": action}
            }

        handler = handlers.get(tool_name)
        if not handler:
            return {"success": False, "message": f"❌ 工具暂不可用: {tool_name}", "data": {"tool": tool_name}}

        field_map = op_cfg.get("field_map", {})
        tool_params = {}
        for in_key, out_key in field_map.items():
            if in_key in filters and filters[in_key] is not None:
                tool_params[out_key] = filters[in_key]

        if limit is not None and "limit" in field_map:
            tool_params[field_map["limit"]] = limit
        if source is not None and "source" in field_map:
            tool_params[field_map["source"]] = source

        result = handler(tool_params)
        if isinstance(result, dict):
            result.setdefault("data", {})
            result["data"]["routed_entity"] = entity_key
            result["data"]["routed_action"] = action
            result["data"]["routed_tool"] = tool_name
        return result

    def _query_metadata(self, entity_key: str, raw_entity: str) -> Dict[str, Any]:
        items = []
        for item in self.schema.get("entities", []):
            if item.get("key") == entity_key:
                items.append({
                    "entity": item.get("key"),
                    "name": item.get("name"),
                    "primary_key": item.get("primary_key"),
                    "aliases": item.get("aliases", []),
                    "relations": [
                        relation for relation in self.schema.get("relations", [])
                        if item.get("name") and item.get("name") in relation
                    ],
                    "supported_actions": list(
                        self.schema.get("operation_mappings", {}).get(entity_key, {}).keys()
                    ) + ["metadata"]
                })
        metadata_skill = DatabaseMetadataSkill({"items": items})
        result = metadata_skill.search(raw_entity or entity_key)
        if not result.get("data", {}).get("items") and items:
            result["data"]["items"] = items
            result["message"] = f"找到 {len(items)} 条元信息"
        return result

    def _resolve_entity_key(self, entity: str) -> str:
        entity_lower = entity.lower()
        for item in self.schema.get("entities", []):
            key = str(item.get("key", "")).strip()
            aliases = [str(x).strip().lower() for x in item.get("aliases", [])]
            name = str(item.get("name", "")).strip().lower()
            if not key:
                continue
            if entity_lower == key.lower() or entity_lower == name or entity_lower in aliases:
                return key
        return ""
