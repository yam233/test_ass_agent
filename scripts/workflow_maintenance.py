"""Bounded local lifecycle maintenance (reference cleanup defaults to preview)."""
import argparse
import json
import time
from agent_core.workflow_store import WorkflowStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".mock_state/platforms.sqlite")
    parser.add_argument(
        "--apply", action="store_true", help="delete eligible refs; otherwise preview"
    )
    args = parser.parse_args()
    store = WorkflowStore(args.db)
    print(
        json.dumps(
            {
                "expired": store.expire_approvals(time.time()),
                "refs": store.gc_refs(time.time(), dry_run=not args.apply),
            }
        )
    )


if __name__ == "__main__":
    main()
