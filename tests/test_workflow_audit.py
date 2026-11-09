import json
from agent_core.workflow import WorkflowRuntime
from tests.test_workflow import CTX, SEED, SequenceModel, call, run, approve


def test_approval_and_receipt_have_durable_correlated_events(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED),{'final':'done'}]))
    state=approve(rt,run(rt.start('seed',CTX)))
    with rt.store.db.connection() as db:
        exists=db.execute("SELECT name FROM sqlite_master WHERE name='workflow_audit'").fetchone()
        assert exists, 'approval audit missing'
        events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM workflow_audit ORDER BY rowid')]
    assert [e['event'] for e in events]==['prepare','approve','start','receipt']
    assert all(e['operator']=='alice' and e['task_id']==state['task_id'] for e in events)
    assert all(e['args_hash'] and e['policy_version'] for e in events)
    rt.platform.actions.complete(state['steps'][0]['result']['data']['action_id'],{'status':'failed','code':'ERROR'})
    with rt.store.db.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_audit WHERE event='receipt'").fetchone()[0]==1


def test_approval_audit_failure_rolls_back_authority(tmp_path):
    import sqlite3
    import pytest
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED)]))
    state=run(rt.start('seed',CTX));aid=state['pending']['action_id']
    with rt.store.db.connection(write=True) as db:
        db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON workflow_audit WHEN NEW.event='approve' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError): approve(rt,state)
    assert rt.platform.actions.get(aid,CTX)['status']=='pending'
    assert not rt.platform.snapshot('gifts')
