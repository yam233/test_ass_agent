"""Scope-checked JSONL evidence export; never exports local provider secrets."""
import argparse
import json
from agent_core.action_store import canonical, scope
from agent_core.workflow_store import WorkflowStore


def export_task(path, task_id, context):
    store = WorkflowStore(path)
    state = store.get(task_id, context)
    events = [{**event, "task_id": task_id} for event in state["trace"]]
    with store.db.connection() as db:
        events.extend(
            {"kind": "audit", **json.loads(row[0])}
            for row in db.execute(
                "SELECT payload FROM workflow_audit WHERE task_id=? AND scope=? ORDER BY rowid",
                (task_id, canonical(scope(context))),
            )
        )
        for fingerprint in state.get("artifact_ids", []):
            row = db.execute(
                "SELECT payload FROM workflow_artifacts WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
            if row:
                events.append(
                    {
                        "kind": "artifact",
                        "fingerprint": fingerprint,
                        "data": json.loads(row[0]),
                    }
                )
    return events


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=".mock_state/platforms.sqlite")
    p.add_argument("--task-id", required=True)
    p.add_argument("--operator", required=True)
    p.add_argument("--session-id", required=True)
    p.add_argument("--env", required=True)
    args = p.parse_args()
    events = export_task(
        args.db,
        args.task_id,
        {"operator": args.operator, "session_id": args.session_id, "env": args.env},
    )
    for event in events:
        print(json.dumps(event, ensure_ascii=False))


if __name__ == "__main__":
    main()
