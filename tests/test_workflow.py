import asyncio
import pytest
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget

CTX={'operator':'alice','session_id':'s','env':'uat'}
SEED={'table':'gifts','user_id':123,'gift_id':301,'quantity':10}

class SequenceModel:
    name='fixture'
    def __init__(self,decisions): self.decisions=iter(decisions); self.calls=0
    async def next(self,messages,context,max_tokens):
        self.calls+=1
        item=next(self.decisions)
        return {**item,'usage':{'total_tokens':10},'model':'fixture','prompt_version':'test'}

def call(tool,args): return {'tool':tool,'args':args}
def run(awaitable): return asyncio.run(awaitable)
def approve(rt,state): return run(rt.resume(state['task_id'],CTX,action_id=state['pending']['action_id'],decision='approve'))

def test_multi_step_seed_query_requires_bound_approval(tmp_path):
    model=SequenceModel([call('seed_test_data',SEED),call('query_data',{'table':'gifts','user_id':123}),{'final':'完成'}])
    rt=WorkflowRuntime(tmp_path/'db',model=model)
    state=run(rt.start('发放后查询',CTX))
    assert state['status']=='approval_wait' and not rt.platform.snapshot('gifts')
    state=approve(rt,state)
    assert state['status']=='completed' and state['stop_reason']=='finished'
    assert len(state['steps'])==2 and state['steps'][1]['result']['data']['total_quantity']==10
    assert len(rt.platform.snapshot('gifts'))==1

def test_denial_and_scope_mismatch_never_write(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED)]))
    state=run(rt.start('发礼物',CTX))
    with pytest.raises(ValueError): run(rt.resume(state['task_id'],{**CTX,'operator':'bob'}))
    with pytest.raises(ValueError): run(rt.resume(state['task_id'],CTX,action_id='wrong',decision='approve'))
    state=run(rt.resume(state['task_id'],CTX,action_id=state['pending']['action_id'],decision='deny'))
    assert state['stop_reason']=='denied' and not rt.platform.snapshot('gifts')

def test_duplicate_tool_call_stops_loop(tmp_path):
    query=call('query_data',{'table':'gifts'})
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([query,query]))
    state=run(rt.start('查询',CTX))
    assert state['stop_reason']=='loop' and len(state['steps'])==1

@pytest.mark.parametrize('budget,reason',[({'max_steps':1},'max_steps'),({'max_tokens':1},'budget'),({'max_seconds':0.001},'timeout')])
def test_budgets_stop_before_unbounded_work(tmp_path,budget,reason):
    class Slow(SequenceModel):
        async def next(self,*args):
            await asyncio.sleep(.01)
            return await super().next(*args)
    rt=WorkflowRuntime(tmp_path/'db',model=Slow([call('query_data',{'table':'gifts'}),{'final':'done'}]))
    state=run(rt.start('查询',CTX,Budget(**budget)))
    assert state['stop_reason']==reason

def test_bad_args_can_repair_once_and_missing_info_pauses(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([
        call('seed_test_data',{**SEED,'quantity':-1}),call('ask_clarification',{'question':'需要几个？'}),
        call('seed_test_data',SEED),{'final':'完成'}]))
    state=run(rt.start('发礼物',CTX))
    assert state['status']=='clarification_wait' and not rt.platform.snapshot('gifts')
    state=run(rt.resume(state['task_id'],CTX,reply='10个'))
    assert approve(rt,state)['status']=='completed'

def test_second_invalid_call_stops(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('query_data',{'table':'x'}),call('query_data',{'table':'y'})]))
    assert run(rt.start('查询',CTX))['stop_reason']=='bad_args'

@pytest.mark.parametrize('fault,reason,attempts',[('f_403','auth',1),('f_5xx','unrecoverable',3),('f_halfseed','partial',1),('f_response_loss','finished',1)])
def test_failure_classification(tmp_path,fault,reason,attempts):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([call('seed_test_data',SEED),{'final':'完成'}]),retry_delays=(0,0))
    state=run(rt.start('发礼物',{**CTX,'fault_id':fault}))
    state=approve(rt,state)
    assert state['stop_reason']==reason
    assert state['tool_calls']==attempts
    assert len(rt.platform.snapshot('gifts'))==(1 if fault in {'f_halfseed','f_response_loss'} else 0)

def test_model_cannot_claim_execution_without_tool_evidence(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([{'final':'已发放10个礼物'}]))
    state=run(rt.start('发10个礼物',CTX))
    assert state['status']=='failed' and state['stop_reason']=='no_evidence'
    assert not rt.platform.snapshot('gifts')

@pytest.mark.parametrize('query,write',[
    (call('query_config',{'key':'gift_multiplier'}),call('update_config',{'key':'gift_multiplier','value':2})),
    (call('query_data',{'table':'gifts'}),call('seed_test_data',SEED))])
def test_same_read_is_valid_after_a_successful_write(tmp_path,query,write):
    rt=WorkflowRuntime(tmp_path/'db',model=SequenceModel([query,write,query,{'final':'done'}]))
    state=run(rt.start('先查询，再修改，再核验',CTX))
    state=approve(rt,state)
    assert state['status']=='completed',state['stop_reason']
    assert len(state['steps'])==3
    assert state['steps'][0]['result']['data']!=state['steps'][2]['result']['data']

def test_wall_clock_budget_checks_synchronous_model_work(tmp_path):
    import time
    class Blocking(SequenceModel):
        async def next(self,*args):
            time.sleep(.03)
            return await super().next(*args)
    rt=WorkflowRuntime(tmp_path/'db',model=Blocking([call('query_data',{'table':'gifts'}),{'final':'done'}]))
    state=run(rt.start('查询',CTX,Budget(max_seconds=.01)))
    assert state['stop_reason']=='timeout' and state['tool_calls']==0
