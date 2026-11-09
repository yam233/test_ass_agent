#!/usr/bin/env python3
"""
统一刷新 Grafana Cookie 的脚本。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business_logic.appearance.grafana_auth import clear_cookie_cache, get_valid_cookies_with_reason


def main() -> int:
    clear_cookie_cache()
    cookies, reason = get_valid_cookies_with_reason()
    if not cookies:
        print(f"FAILED: 无法获取有效的 Grafana Cookie; reason={reason}")
        return 1
    print(f"OK: 已获取有效 Grafana Cookie; reason={reason}")
    print(cookies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
