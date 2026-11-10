import json
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_context import build_context
from agent_core.workflow_contracts import catalog
from tests.test_workflow import CTX, SequenceModel, call, run


def completed_read(path,context=CTX):
    rt=WorkflowRuntime(path,model=SequenceModel([call('query_config',{'key':'gift_multiplier'}),{'final':'done'}]))
    return rt,run(rt.start('查询配置',context))


def test_session_history_is_persistent_scoped_and_not_permission(tmp_path):
    from agent_core.workflow_memory import SessionMemory
    rt,s=completed_read(tmp_path/'db')
    memory=SessionMemory(rt.store.db)
    rows=memory.recent(s['scope'],exclude='next')
    assert rows[0]['task_id']==s['task_id']
    assert rows[0]['facts'][0]['tool']=='query_config'
    assert 'allowed_tools' not in json.dumps(rows)
    assert memory.recent(['alice','different','uat'],exclude='next')==[]
    assert memory.recent(['bob','s','uat'],exclude='next')==[]
    assert memory.recent(['alice','s','prod'],exclude='next')==[]
    assert memory.recent(s['scope'],exclude=s['task_id'])==[]
    assert memory.recent(s['scope'],exclude='next',now=10**12)==[]


def test_context_preserves_chronological_user_correction_and_sources(tmp_path):
    rt,s=completed_read(tmp_path/'db')
    s.update(agent_protocol=2,replies=['改成3个'],understanding={'user_revision':1,'goals':[]},
             session_memory=[], steps=[
                 {'seq':0,'user_revision':0,'tool':'ask_clarification','args':{'question':'几个'},'result':{'success':False,'seq':0}},
                 {'seq':1,'user_revision':1,'tool':'query_data','args':{'table':'gifts'},'result':{'success':True,'seq':1,'data':{'total_quantity':0}}}])
    built=build_context(s,catalog())
    messages=built['messages']; text=[m.get('content','') for m in messages]
    reply=next(i for i,t in enumerate(text) if '[u1]' in t)
    first=next(i for i,m in enumerate(messages) if m.get('tool_call_id')=='call_0')
    second=next(i for i,m in enumerate(messages) if m.get('tool_call_id')=='call_1')
    assert first<reply<second
    assert '[u0]' in ''.join(text)


def test_compression_keeps_goal_last_write_and_latest_correction(tmp_path):
    rt,s=completed_read(tmp_path/'db')
    s.update(agent_protocol=2,replies=['目标用户改成456'], session_memory=[],
             understanding={'user_revision':1,'goals':[{'id':'g1','args':{'user_id':456}}]})
    s['steps']=[{'seq':i,'user_revision':0,'tool':'query_data','args':{'table':'gifts'},
                 'result':{'success':True,'data':{'rows':['x'*1000]*5,'ref_id':f'ref{i}'}}} for i in range(20)]
    s['steps'][5].update(tool='seed_test_data',args={'user_id':123,'quantity':10},
                        result={'success':True,'data':{'actual':10,'batch_id':'batch-1'}})
    built=build_context(s,[],input_limit_bytes=7000)
    text=json.dumps(built['messages'],ensure_ascii=False)
    assert 'batch-1' in text and '456' in text
    assert built['context_bytes']['total']<=7000
    assert built['compaction_events']
