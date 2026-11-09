"""
通用批量执行器

用于统一处理：
1. 多操作拆分后的逐条执行与汇总
2. 查询类批量参数拆分后的逐条执行与汇总
"""
from typing import Any, Awaitable, Callable, Dict, List, Optional


class BatchQueryExecutor:
    """批量执行与汇总工具"""

    @staticmethod
    def _to_items(raw_value: Any) -> List[Any]:
        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            return [item for item in raw_value if item not in ("", None)]
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            if not stripped:
                return []
            if "," in stripped:
                return [item.strip() for item in stripped.split(",") if item.strip()]
            if "，" in stripped:
                return [item.strip() for item in stripped.split("，") if item.strip()]
            return [stripped]
        return [raw_value]

    @classmethod
    def build_batch_param_sets(cls, params: Dict[str, Any], skill_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        根据 skills_registry 里的 batch_config 构造批量参数集合。
        batch_config 支持：
        - 单规则：{"enabled": true, "source_param": "...", "target_param": "..."}
        - 多规则：{"enabled": true, "rules": [{"source_param": "...", "target_param": "..."}]}
        """
        rules = cls._resolve_batch_rules(params, skill_config or {})
        if not rules:
            return []

        param_sets: List[Dict[str, Any]] = [params.copy()]
        expanded = False
        for rule in rules:
            source_param = rule.get("source_param")
            target_param = rule.get("target_param")
            if not source_param or not target_param:
                continue
            items = cls._to_items(params.get(source_param))
            if len(items) <= 1:
                # 单值不需要批量展开
                continue
            expanded = True
            next_sets: List[Dict[str, Any]] = []
            for base in param_sets:
                for item in items:
                    item_params = base.copy()
                    item_params[target_param] = item
                    # 移除源参数，避免重复处理
                    item_params.pop(source_param, None)
                    next_sets.append(item_params)
            param_sets = next_sets

        return param_sets if expanded else []

    @classmethod
    def _resolve_batch_rules(cls, params: Dict[str, Any], skill_config: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        优先使用显式 batch_config；若未配置则进行通用推断。
        推断规则：
        1) *_ids -> *_id（且 target 在 param_schema 中存在）
        2) string 参数包含逗号时，按同名参数拆分（用于关键词类查询）
        """
        batch_cfg = skill_config.get("batch_config", {})
        if batch_cfg and batch_cfg.get("enabled", False):
            explicit_rules = batch_cfg.get("rules")
            if explicit_rules:
                return explicit_rules
            source_param = batch_cfg.get("source_param")
            target_param = batch_cfg.get("target_param")
            if source_param and target_param:
                return [{"source_param": source_param, "target_param": target_param}]

        inferred_rules: List[Dict[str, str]] = []
        param_schema = skill_config.get("param_schema", {})

        for param_name, raw_value in params.items():
            if raw_value in (None, ""):
                continue

            items = cls._to_items(raw_value)
            if len(items) <= 1:
                continue

            # 规则1：xxx_ids -> xxx_id
            if param_name.endswith("_ids"):
                target_param = f"{param_name[:-1]}"  # ids -> id
                if target_param in param_schema:
                    inferred_rules.append({
                        "source_param": param_name,
                        "target_param": target_param
                    })
                    continue

            # 规则2：字符串参数带逗号，同名拆分
            schema_def = param_schema.get(param_name, {})
            if schema_def.get("type") == "string":
                inferred_rules.append({
                    "source_param": param_name,
                    "target_param": param_name
                })

        return inferred_rules

    @staticmethod
    async def run_operations(
        operations: List[str],
        run_operation: Callable[[str, int], Awaitable[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """统一执行多条文本操作并汇总结果"""
        results = []
        success_count = 0
        failed_count = 0

        for index, operation in enumerate(operations, start=1):
            try:
                result = await run_operation(operation, index)
                if result.get("success"):
                    success_count += 1
                    results.append({
                        "index": index,
                        "operation": operation,
                        "status": "success",
                        "result": result
                    })
                else:
                    failed_count += 1
                    results.append({
                        "index": index,
                        "operation": operation,
                        "status": "failed",
                        "error": result.get("message", "未知错误")
                    })
            except Exception as e:
                failed_count += 1
                results.append({
                    "index": index,
                    "operation": operation,
                    "status": "failed",
                    "error": str(e)
                })

        return {
            "success": True,
            "data": {
                "operation_count": len(operations),
                "success_count": success_count,
                "failed_count": failed_count,
                "operations": results
            }
        }

    @staticmethod
    async def run_batch_queries(
        param_sets: List[Dict[str, Any]],
        run_query: Callable[[Dict[str, Any], int], Awaitable[Dict[str, Any]]],
        label_param: Optional[str] = None
    ) -> Dict[str, Any]:
        """统一执行批量查询参数集并汇总结果"""
        results = []
        success_count = 0
        failed_count = 0

        for index, item_params in enumerate(param_sets, start=1):
            try:
                result = await run_query(item_params, index)
                label = item_params.get(label_param) if label_param else None
                if result.get("success"):
                    success_count += 1
                    results.append({
                        "index": index,
                        "label": label,
                        "params": item_params,
                        "status": "success",
                        "result": result
                    })
                else:
                    failed_count += 1
                    results.append({
                        "index": index,
                        "label": label,
                        "params": item_params,
                        "status": "failed",
                        "error": result.get("message", "未知错误")
                    })
            except Exception as e:
                failed_count += 1
                results.append({
                    "index": index,
                    "label": item_params.get(label_param) if label_param else None,
                    "params": item_params,
                    "status": "failed",
                    "error": str(e)
                })

        return {
            "success": True,
            "data": {
                "item_count": len(param_sets),
                "success_count": success_count,
                "failed_count": failed_count,
                "items": results
            }
        }
