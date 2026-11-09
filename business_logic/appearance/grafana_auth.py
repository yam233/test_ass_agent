"""
Grafana Cookie 管理（回滚版：仅使用现有 GRAFANA_COOKIES）。
"""
import os
import time
from typing import Dict, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

GRAFANA_API_BASE = os.getenv("GRAFANA_API_BASE", "https://internal.example.invalid")
GRAFANA_VALIDATE_API = os.getenv(
    "GRAFANA_VALIDATE_API",
    f"{GRAFANA_API_BASE}/api/v2/admin/user/appearance/manage",
)
COOKIE_TTL_SECONDS = int(os.getenv("GRAFANA_COOKIE_TTL", "3600"))

_cookie_cache = {"cookies": "", "timestamp": 0.0}


def _env_bool(name: str, default: bool = False) -> bool:
    """从环境变量读取布尔值。"""
    value = os.getenv(name)
    if value is None:
        return default
    value_lower = value.strip().lower()
    if value_lower in {"1", "true", "yes", "on"}:
        return True
    elif value_lower in {"0", "false", "no", "off"}:
        return False
    else:
        return default


def get_grafana_config() -> dict:
    """获取Grafana配置"""
    return {
        "enabled": _env_bool("GRAFANA_ENABLED", False),  # 默认关闭
        "fallback_direct": _env_bool("GRAFANA_FALLBACK_DIRECT", True),
    }


def is_grafana_enabled() -> bool:
    """检查Grafana功能是否启用"""
    return get_grafana_config()["enabled"]


def is_grafana_fallback_enabled() -> bool:
    """检查Grafana回退功能是否启用"""
    return get_grafana_config()["fallback_direct"]

_cookie_cache = {"cookies": "", "timestamp": 0.0}


def clear_cookie_cache() -> None:
    _cookie_cache["cookies"] = ""
    _cookie_cache["timestamp"] = 0.0


def _is_cookie_expired() -> bool:
    return (time.time() - _cookie_cache["timestamp"]) > COOKIE_TTL_SECONDS


def _cache_cookies(cookies: str) -> None:
    _cookie_cache["cookies"] = cookies
    _cookie_cache["timestamp"] = time.time()


def _get_cached_cookies() -> Optional[str]:
    if _cookie_cache["cookies"] and not _is_cookie_expired():
        return _cookie_cache["cookies"]
    return None


def _cookie_str_to_dict(cookies: str) -> Dict[str, str]:
    cookie_dict: Dict[str, str] = {}
    for cookie in cookies.split("; "):
        if "=" in cookie:
            key, value = cookie.split("=", 1)
            cookie_dict[key] = value
    return cookie_dict


def test_cookie_validity_with_reason(cookies: str) -> Tuple[bool, str]:
    if not cookies:
        return False, "cookie_empty"
    try:
        resp = requests.get(
            GRAFANA_VALIDATE_API,
            headers={"accept": "application/json", "content-type": "application/json"},
            cookies=_cookie_str_to_dict(cookies),
            timeout=10,
        )
        if resp.status_code in (401, 403):
            return False, f"cookie_unauthorized_{resp.status_code}"
        return True, f"cookie_valid_{resp.status_code}"
    except Exception as exc:
        return False, f"cookie_validate_exception:{exc}"


def test_cookie_validity(cookies: str) -> bool:
    ok, _ = test_cookie_validity_with_reason(cookies)
    return ok


def get_authenticated_cookies_with_reason() -> Tuple[str, str]:
    cached = _get_cached_cookies()
    if cached:
        return cached, "from_cache"

    env_cookies = os.getenv("GRAFANA_COOKIES", "").strip()
    if env_cookies:
        _cache_cookies(env_cookies)
        return env_cookies, "from_env"
    return "", "missing_env_cookie"


def get_authenticated_cookies() -> str:
    cookies, _ = get_authenticated_cookies_with_reason()
    return cookies


def get_valid_cookies_with_reason() -> Tuple[str, str]:
    cached = _get_cached_cookies()
    if cached:
        valid, reason = test_cookie_validity_with_reason(cached)
        if valid:
            return cached, "valid_cache"
        clear_cookie_cache()
        return "", f"invalid_cache:{reason}"

    fresh, source_reason = get_authenticated_cookies_with_reason()
    if not fresh:
        return "", source_reason
    valid, valid_reason = test_cookie_validity_with_reason(fresh)
    if valid:
        return fresh, f"valid_{source_reason}"
    return "", f"{source_reason};{valid_reason}"


def get_valid_cookies() -> str:
    cookies, _ = get_valid_cookies_with_reason()
    return cookies
