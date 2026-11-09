"""Inspect/reset the synthetic environment: python -m scripts.mock_state snapshot|actions|reset."""
import argparse
import json
import os
from agent_core.mock_platforms import MockPlatforms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "actions", "reset"])
    parser.add_argument("--db", default=os.getenv("MOCK_DB_PATH", ".mock_state/platforms.sqlite"))
    args = parser.parse_args()
    platforms = MockPlatforms(args.db)
    if args.action == "reset":
        platforms.reset()
    data = platforms.actions.list_actions() if args.action == "actions" else {table: platforms.snapshot(table) for table in ("gifts", "events", "script_runs")}
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
