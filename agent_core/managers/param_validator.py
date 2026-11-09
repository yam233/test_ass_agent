"""
Schema-driven parameter validation shared by sync and async agents.

The skills registry uses a small JSON-schema-like contract. Keep the
validation here so Agent paths do not drift apart.
"""
from typing import Any, Dict, Optional
import re


class ParamValidator:
    """Validate and normalize parameters from a skill param_schema."""

    @classmethod
    def validate(cls, params: Dict[str, Any], param_schema: Dict[str, Any]) -> Dict[str, Any]:
        errors = []
        validated_params = params.copy()

        for param_name, param_def in param_schema.items():
            required = param_def.get("required", False)
            param_type = param_def.get("type")

            if cls._is_conditionally_optional(param_name, required, validated_params):
                continue

            if required and cls._is_missing(validated_params.get(param_name)):
                errors.append(f"缺少必填参数: {param_name}")
                continue

            if param_name not in validated_params:
                continue

            value = validated_params[param_name]
            converted, type_error = cls._convert_type(param_name, value, param_type)
            if type_error:
                errors.append(type_error)
                continue

            validated_params[param_name] = converted

            enum_values = param_def.get("enum") or param_def.get("validation", {}).get("enum")
            if enum_values and converted not in enum_values:
                errors.append(param_def.get("message", f"参数 {param_name} 必须是 {enum_values} 之一"))
                continue

            validation = param_def.get("validation", {})
            if validation:
                error = cls._validate_rules(param_name, converted, validation)
                if error:
                    errors.append(error)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "params": validated_params
        }

    @staticmethod
    def _is_missing(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    @staticmethod
    def _is_conditionally_optional(
        param_name: str,
        required: bool,
        validated_params: Dict[str, Any]
    ) -> bool:
        # Backward-compatible special cases in the existing gift skills.
        if param_name == "gift_id" and required is False:
            if validated_params.get("gift_nums") or validated_params.get("gift_ids"):
                return True

        if param_name == "user_id" and required:
            if validated_params.get("user_ids"):
                return True

        return False

    @classmethod
    def _convert_type(cls, param_name: str, value: Any, param_type: Optional[str]):
        if param_type == "integer":
            if isinstance(value, bool):
                return None, f"参数 {param_name} 类型错误，期望: integer，实际: bool"
            if not isinstance(value, int):
                try:
                    return int(value), None
                except (ValueError, TypeError):
                    return None, f"参数 {param_name} 类型错误，期望: integer，实际: {type(value).__name__}"
            return value, None

        if param_type == "string":
            if isinstance(value, (dict, list)):
                return None, f"参数 {param_name} 类型错误，期望: string，实际: {type(value).__name__}"
            return str(value), None

        if param_type == "array":
            if isinstance(value, list):
                return value, None
            if isinstance(value, str):
                items = cls._split_list_string(value)
                if items:
                    return items, None
            return None, f"参数 {param_name} 类型错误，期望: array，实际: {type(value).__name__}"

        if param_type == "object":
            if isinstance(value, dict):
                return value, None
            return None, f"参数 {param_name} 类型错误，期望: object，实际: {type(value).__name__}"

        if param_type == "number":
            if isinstance(value, bool):
                return None, f"参数 {param_name} 类型错误，期望: number，实际: bool"
            if isinstance(value, (int, float)):
                return value, None
            try:
                return float(value), None
            except (ValueError, TypeError):
                return None, f"参数 {param_name} 类型错误，期望: number，实际: {type(value).__name__}"

        if param_type == "boolean":
            if isinstance(value, bool):
                return value, None
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "on", "是"}:
                    return True, None
                if lowered in {"false", "0", "no", "off", "否"}:
                    return False, None
            return None, f"参数 {param_name} 类型错误，期望: boolean，实际: {type(value).__name__}"

        return value, None

    @staticmethod
    def _split_list_string(value: str):
        stripped = value.strip()
        if not stripped:
            return []
        if "," in stripped:
            return [item.strip() for item in stripped.split(",") if item.strip()]
        if "，" in stripped:
            return [item.strip() for item in stripped.split("，") if item.strip()]
        return []

    @staticmethod
    def _validate_rules(param_name: str, value: Any, rules: dict) -> Optional[str]:
        if "min" in rules and isinstance(value, (int, float)):
            if value < rules["min"]:
                return rules.get("message", f"参数 {param_name} 小于最小值 {rules['min']}")

        if "max" in rules and isinstance(value, (int, float)):
            if value > rules["max"]:
                return rules.get("message", f"参数 {param_name} 大于最大值 {rules['max']}")

        if "pattern" in rules:
            if not re.match(rules["pattern"], str(value)):
                return rules.get("message", f"参数 {param_name} 格式不正确")

        return None
