import httpx
import pytest
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget
from agent_core.workflow_model import ModelResponseError
from tests.test_workflow import CTX, call, run

class Attempts:
    name='transport_fixture'
    def __init__(self, failures): self.failures=list(failures); self.caps=[]
    async def next(self,messages,context,max_tokens):
        self.caps.append(max_tokens)
        if self.failures:
            err=self.failures.pop(0)
            if err=='length': raise ModelResponseError('truncated',{'total_tokens':10},'length')
            response=httpx.Response(err,request=httpx.Request('POST','https://example.invalid/v1'))
            raise httpx.HTTPStatusError('provider error',request=response.request,response=response)
        done=any(m['role']=='tool' for m in messages)
        return {**({'final':'done'} if done else call('query_data',{'table':'gifts'})),'usage':{'total_tokens':10}}

@pytest.mark.parametrize('failures', [[503],[429],['length']])
def test_provider_retry_accounts_every_attempt(tmp_path,failures):
    model=Attempts(failures)
    rt=WorkflowRuntime(tmp_path/'db',model=model,retry_delays=(0,0))
    state=run(rt.start('read',CTX))
    assert state['status']=='completed'
    assert state['model_calls']==3
    assert len([e for e in state['trace'] if e['kind']=='model'])==3
    assert state['tokens']>=state['reported_tokens']
    if failures==['length']: assert model.caps[:2]==[1024,2048]
    assert all(e['prompt_ver']!='workflow-v1' for e in state['trace'] if e['kind']=='model')

@pytest.mark.parametrize('failures,attempts', [([401],1),([503,503,503,503],3),(['length','length'],2)])
def test_retry_limits_and_nonretryable_auth(tmp_path,failures,attempts):
    model=Attempts(failures);rt=WorkflowRuntime(tmp_path/'db',model=model,retry_delays=(0,0))
    state=run(rt.start('read',CTX))
    assert state['stop_reason']=='model_error'
    assert state['model_calls']==attempts
    assert not rt.platform.snapshot('gifts')


def test_retry_never_exceeds_step_budget(tmp_path):
    model=Attempts([503]);rt=WorkflowRuntime(tmp_path/'db',model=model,retry_delays=(0,0))
    state=run(rt.start('read',CTX,Budget(max_steps=1)))
    assert state['model_calls']==1 and state['stop_reason']=='max_steps'


def test_artifact_tracks_effective_prompt_without_credentials(tmp_path,monkeypatch):
    from agent_core import workflow_model
    from agent_core.model_call import artifact
    from agent_core.workflow_model import NativeModel
    class Settings:
        def _setting(self,name): return {'model':'demo','base_url':'https://user:secret@example.test/v1?key=secret','api_key':'secret'}[name]
    model=NativeModel(Settings())
    before=artifact(model,1024)
    monkeypatch.setattr(workflow_model,'SYSTEM',workflow_model.SYSTEM+'\nnew instruction')
    after=artifact(model,1024)
    assert before!=after
    assert 'secret' not in str(after)
