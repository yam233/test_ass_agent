import asyncio
import json
import httpx
import pytest
from agent_core.workflow_contracts import catalog, normalize
from agent_core.workflow_platform import WorkflowPlatform
from agent_core.workflow_model import NativeModel
from agent_core.langgraph_agent.llm import DeepSeekLLM
from agent_core.layers.local_config import LocalConfigLayer

CTX = {'operator':'test','session_id':'s','env':'uat'}

def write(p, tool, args):
    a = p.prepare(tool, args, CTX)
    p.actions.approve(a['action_id'], CTX)
    return p.execute(tool, args, {**CTX, 'action_id':a['action_id']})

def test_catalog_has_narrow_contracts_and_rejects_invalid_inputs():
    tools = catalog()
    assert len(tools) == 10
    assert all('不要用于' in t['function']['description'] for t in tools)
    for args in ({'table':'users','user_id':1,'gift_id':2,'quantity':3},
                 {'table':'gifts','user_id':1,'gift_id':2,'quantity':'3'},
                 {'table':'gifts','user_id':1,'gift_id':2,'quantity':10001}):
        with pytest.raises(ValueError): normalize('seed_test_data', args)

def test_seed_cleanup_is_approved_idempotent_and_batch_scoped(tmp_path):
    p = WorkflowPlatform(tmp_path/'state.db')
    args = {'table':'gifts','user_id':1,'gift_id':2,'quantity':10}
    assert p.execute('seed_test_data', args, CTX)['code'] == 'CONFIRM_REQUIRED'
    first, second = write(p,'seed_test_data',args), write(p,'seed_test_data',args)
    batch = first['data']['batch_id']
    cleaned = write(p,'cleanup_data',{'batch_id':batch})
    assert cleaned['data']['actual'] == 10
    assert sum(r['quantity'] for r in p.snapshot('gifts')) == 10
    assert p.snapshot('gifts')[0]['batch_id'] == second['data']['batch_id']

def test_config_rollback_does_not_overwrite_later_change(tmp_path):
    p = WorkflowPlatform(tmp_path/'state.db')
    first = write(p,'update_config',{'key':'gift_multiplier','value':2})
    write(p,'update_config',{'key':'gift_multiplier','value':3})
    r = write(p,'rollback_config',{'change_id':first['data']['action_id']})
    assert r['code'] == 'CONFLICT'
    assert p.execute('query_config',{'key':'gift_multiplier'},CTX)['data']['value'] == 3

def test_config_roundtrip_and_cleanup_scope(tmp_path):
    p = WorkflowPlatform(tmp_path/'state.db')
    change = write(p,'update_config',{'key':'gift_multiplier','value':2})
    assert write(p,'rollback_config',{'change_id':change['data']['action_id']})['success']
    assert p.execute('query_config',{'key':'gift_multiplier'},CTX)['data']['value'] == 1
    batch = write(p,'seed_test_data',{'table':'gifts','user_id':1,'gift_id':2,'quantity':10})['data']['batch_id']
    with pytest.raises(ValueError):
        p.prepare('cleanup_data',{'batch_id':batch},{**CTX,'operator':'other'})

def test_native_function_call_and_usage(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        assert body['tools'] and body['parallel_tool_calls'] is False
        assert body['max_tokens'] == 128
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'id':'c1','type':'function','function':{'name':'query_data','arguments':'{"table":"gifts"}'}}]}}], 'usage':{'prompt_tokens':21,'completion_tokens':8,'total_tokens':29}})
    llm = DeepSeekLLM(LocalConfigLayer(str(tmp_path/'empty')),transport=httpx.MockTransport(handler))
    llm._setting = lambda key: {'api_key':'test','base_url':'https://example.test/v1','model':'test'}[key]
    result = asyncio.run(NativeModel(llm).next([{'role':'user','content':'查询礼物'}],CTX,128))
    assert result['tool'] == 'query_data' and result['usage']['total_tokens'] == 29

def test_truncated_model_response_retains_usage_for_accounting(tmp_path):
    from agent_core.workflow_model import ModelResponseError
    def handler(request):
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':''}}],'usage':{'total_tokens':200}})
    llm=DeepSeekLLM(LocalConfigLayer(str(tmp_path/'empty')),transport=httpx.MockTransport(handler))
    llm._setting=lambda key:{'api_key':'test','base_url':'https://example.test/v1','model':'test'}[key]
    with pytest.raises(ModelResponseError) as error:
        asyncio.run(NativeModel(llm).next([{'role':'user','content':'x'}],CTX,128))
    assert error.value.usage['total_tokens']==200
    assert error.value.finish_reason=='length'

def test_config_approval_rejects_a_changed_preview(tmp_path):
    p=WorkflowPlatform(tmp_path/'db')
    args={'key':'gift_multiplier','value':2}
    pending=p.prepare('update_config',args,CTX)
    write(p,'update_config',{'key':'gift_multiplier','value':3})
    p.actions.approve(pending['action_id'],CTX)
    result=p.execute('update_config',args,{**CTX,'action_id':pending['action_id']})
    assert result['code']=='CONFLICT'
    assert p.execute('query_config',{'key':'gift_multiplier'},CTX)['data']['value']==3
