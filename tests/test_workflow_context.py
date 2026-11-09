import importlib.util
import json
import pytest
from agent_core.action_store import ActionError, canonical
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_contracts import catalog
from tests.test_workflow import CTX, SequenceModel, call, run


def builder():
    assert importlib.util.find_spec('agent_core.workflow_context'), 'context builder missing'
    from agent_core.workflow_context import build_context
    return build_context


def test_long_history_is_bounded_and_tool_pairs_preserved():
    build=builder()
    state={'input':'核验最终值','replies':['保留用户约束'],'steps':[
        {'tool':'query_data','args':{'table':'gifts'},'result':{'code':'OK','success':True,'data':{'rows':[{'text':'中'*1000}]}}}
        for i in range(200)]}
    result=build(state,catalog())
    assert result['context_bytes']['total']<=32768
    messages=result['messages']
    assert messages[0]['content']=='核验最终值' and messages[-1]['content']=='保留用户约束'
    assert not any(m['role']=='system' for m in messages)
    for i,m in enumerate(messages):
        if m['role']=='tool':
            assert messages[i-1]['role']=='assistant'
            assert m['tool_call_id']==messages[i-1]['tool_calls'][0]['id']
    assert result['compaction_events']


def test_necessary_input_overflow_fails_explicitly():
    with pytest.raises(ActionError,match='上下文'):
        builder()({'input':'中'*12000,'replies':[],'steps':[]},catalog())


def test_twelve_step_workflow_keeps_latest_observation(tmp_path):
    decisions=[call('query_data',{'table':'gifts','user_id':i}) for i in range(1,13)]+[{'final':'done'}]
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel(decisions))
    state=run(rt.start('查询十二个用户',CTX))
    assert state['status']=='completed' and len(state['steps'])==12
    traces=[t for t in state['trace'] if t['kind']=='model']
    assert all(t.get('context_bytes',{}).get('total',0)>0 for t in traces)
