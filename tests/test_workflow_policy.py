import json
import pytest
from agent_core.action_store import ActionError
from agent_core.workflow import WorkflowRuntime
from tests.test_workflow import CTX, SEED, SequenceModel, call, run, approve

@pytest.mark.parametrize('context', [{}, {'operator':'alice'}, {'env':'uat'}])
def test_write_requires_explicit_identity_and_environment(tmp_path, context):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED)]))
    state=run(rt.start('seed',context))
    assert state['status']=='failed'
    assert not rt.platform.actions.list_actions()


def test_resume_cannot_remove_tool_restriction(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('ask_clarification',{'question':'next?'}),call('seed_test_data',SEED)]))
    state=run(rt.start('clarify',{**CTX,'allowed_tools':['ask_clarification','query_data']}))
    state=run(rt.resume(state['task_id'],CTX,reply='seed'))
    assert state['status']=='failed' and not rt.platform.snapshot('gifts')
    assert not rt.platform.actions.list_actions()


def test_server_revocation_blocks_existing_approval(tmp_path,monkeypatch):
    path=tmp_path/'policy.json'
    path.write_text(json.dumps({'operators':{'alice':['seed_test_data']},'cleanup_max_quantity':1000}))
    monkeypatch.setenv('WORKFLOW_POLICY_PATH',str(path))
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED)]))
    state=run(rt.start('seed',CTX))
    path.write_text(json.dumps({'operators':{'alice':[]},'cleanup_max_quantity':1000}))
    with pytest.raises(ActionError): approve(rt,state)
    assert not rt.platform.snapshot('gifts')


def test_cleanup_requires_bound_effect_confirmation(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED),{'final':'done'}]))
    seed=approve(rt,run(rt.start('seed',CTX)))
    batch=seed['steps'][0]['result']['data']['batch_id']
    rt.model=SequenceModel([call('cleanup_data',{'batch_id':batch}),{'final':'done'}])
    state=run(rt.start('delete',CTX))
    with pytest.raises(ActionError): approve(rt,state)
    result=run(rt.resume(state['task_id'],CTX,action_id=state['pending']['action_id'],decision='approve',confirm_effect='delete_batch',snapshot_hash=state['pending']['snapshot_hash']))
    assert result['status']=='completed' and rt.platform.snapshot('gifts')==[]


def test_cleanup_threshold_rejects_before_action(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',{**SEED,'quantity':1001}),{'final':'done'}]))
    seed=approve(rt,run(rt.start('seed',CTX)))
    batch=seed['steps'][0]['result']['data']['batch_id']
    rt.model=SequenceModel([call('cleanup_data',{'batch_id':batch})])
    result=run(rt.start('delete',CTX))
    assert result['status']=='failed'
    assert len(rt.platform.actions.list_actions())==1


def test_cleanup_preview_change_never_deletes(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED),{'final':'done'}]))
    seed=approve(rt,run(rt.start('seed',CTX)))
    batch=seed['steps'][0]['result']['data']['batch_id']
    rt.model=SequenceModel([call('cleanup_data',{'batch_id':batch})])
    state=run(rt.start('delete',CTX))
    with rt.platform.actions.connection(write=True) as db:
        row=json.loads(db.execute('SELECT payload FROM gifts WHERE id=?',(batch,)).fetchone()[0])
        row['quantity']=11
        db.execute('UPDATE gifts SET payload=? WHERE id=?',(json.dumps(row),batch))
    state=run(rt.resume(state['task_id'],CTX,action_id=state['pending']['action_id'],decision='approve',confirm_effect='delete_batch',snapshot_hash=state['pending']['snapshot_hash']))
    assert state['result']['code']=='CONFLICT'
    assert rt.platform.snapshot('gifts')[0]['quantity']==11
