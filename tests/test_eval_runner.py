import importlib.util
import json
import pytest
from tests.test_workflow import run, call, CTX


def runner():
    assert importlib.util.find_spec('evals.runner'), 'unified runner missing'
    from evals.runner import evaluate
    return evaluate


def test_fixture_and_backpack_reports_are_separate_and_comparable():
    evaluate=runner()
    result=run(evaluate(suite='workflow',model='fixture',repeat=1))
    assert result['passed']==result['total'] and result['total']>=36
    assert result['mode']=='runtime_fixture'
    assert result['metrics']['decision_accuracy'] is None
    assert len([r for r in result['cases'] if r.get('steps',0)>=3])>=6
    backpack=run(evaluate(suite='backpack',model='fixture',repeat=1))
    assert backpack['passed']==backpack['total']==9
    with pytest.raises(ValueError,match='baseline|基线'):
        run(evaluate(suite='workflow',model='fixture',repeat=1,baseline=backpack))


def test_chaos_reports_containment_and_false_rejection():
    report=run(runner()(suite='workflow',model='chaos',repeat=2,seed=17))
    assert report['mode']=='runtime_chaos'
    assert report['metrics']['unsafe_escape_rate']==0
    assert report['metrics']['normal_false_rejection_rate']==0
    assert report['metrics']['runtime_containment']==1


def test_remote_requires_explicit_budget():
    with pytest.raises(ValueError,match='预算|budget'):
        run(runner()(suite='workflow',model='remote',repeat=1))


def test_replay_maps_dynamic_ids_and_rejects_changed_observation():
    runner()
    from evals.models import RecordingModel,ReplayModel,ReplayIncompatible
    class Model:
        async def next(self,messages,context,max_tokens):
            rid=json.loads(messages[-1]['content'])['data']['ref_id']
            return {**call('read_ref',{'ref_id':rid}),'usage':{'total_tokens':10}}
    source='11111111-1111-4111-8111-111111111111';target='22222222-2222-4222-8222-222222222222'
    message=lambda rid,n:[{'role':'tool','tool_call_id':'call_0','content':json.dumps({'data':{'ref_id':rid,'row_count':n}})}]
    recorder=RecordingModel(Model())
    run(recorder.next(message(source,60),CTX,1024))
    replay=ReplayModel(recorder.records)
    result=run(replay.next(message(target,60),CTX,1024))
    assert result['args']['ref_id']==target
    with pytest.raises(ReplayIncompatible):
        run(ReplayModel(recorder.records).next(message(target,61),CTX,1024))


def test_read_fault_retries_and_exports_are_scoped(tmp_path):
    from agent_core.workflow import WorkflowRuntime
    from agent_core.action_store import ActionError
    from tests.test_workflow import SequenceModel
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('query_data',{'table':'gifts'}),{'final':'done'}]),retry_delays=(0,0))
    state=run(rt.start('read',{**CTX,'fault_id':'f_5xx','fault_count':1}))
    assert state['tool_calls']==2 and state['status']=='completed'
    from scripts.export_workflow_trace import export_task
    events=export_task(tmp_path/'db',state['task_id'],CTX)
    assert any(e['kind']=='model' for e in events)
    assert all('api_key' not in json.dumps(e).lower() for e in events)
    with pytest.raises(ActionError): export_task(tmp_path/'db',state['task_id'],{**CTX,'operator':'bob'})


def test_recorded_chains_replay_without_live_model():
    evaluate=runner()
    recorded=run(evaluate(record=True))
    recordings={f"{r['case_id']}:{r['trial']-1}":r['records'] for r in recorded['cases'] if r.get('records')}
    replay=run(evaluate(model='replay',replay=recordings))
    assert replay['mode']=='historical_replay' and replay['passed']==replay['total']==7
