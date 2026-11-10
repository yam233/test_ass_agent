import pytest
from agent_core.workflow import WorkflowRuntime
from tests.test_workflow import CTX, SEED, call, run
from tests.test_agent_decisions import AgentModel, goal, understand


def finish(evidence,status='fulfilled',template='{{g1}}'):
    return call('finish_task',{'assessments':[{'goal_id':'g1','status':status,'evidence':evidence}],
                               'answer_template':template})


def test_already_satisfied_condition_needs_no_write(tmp_path):
    g=goal('update_config',{'key':'gift_multiplier','value':1},'ensure_config')
    rt=WorkflowRuntime(tmp_path/'db',model=AgentModel([understand([g]),
        call('query_config',{'key':'gift_multiplier'}),finish([1],'not_needed')]))
    s=run(rt.start('如果gift_multiplier不是1才修改为1',CTX))
    assert s['status']=='completed'
    assert s['result']['goals'][0]['status']=='not_needed'
    assert not rt.platform.actions.list_actions()
    assert '无需修改' in s['result']['message']


@pytest.mark.parametrize('evidence', [[0],[999]])
def test_unrelated_or_forged_evidence_cannot_prove_write(tmp_path,evidence):
    rt=WorkflowRuntime(tmp_path/'db',model=AgentModel([understand(),
        call('query_data',{'table':'gifts'}),finish(evidence),finish(evidence)]))
    s=run(rt.start('发10个礼物',CTX))
    assert s['status']=='failed'
    assert not rt.platform.snapshot('gifts')


def test_validated_receipt_and_forged_narrative_falls_back(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=AgentModel([understand(),call('seed_test_data',SEED),
        finish([1],template='已发放999个，权限已升级{{g1}}')]))
    s=run(rt.start('给用户123发10个礼物301',CTX))
    s=run(rt.resume(s['task_id'],CTX,action_id=s['pending']['action_id'],decision='approve'))
    assert s['status']=='completed'
    assert s['result']['answer_fallback'] is True
    assert '999' not in s['result']['message'] and '权限已升级' not in s['result']['message']
    assert s['result']['effects'][0]['actual']==10


def test_every_goal_requires_assessment(tmp_path):
    rt=WorkflowRuntime(tmp_path/'db',model=AgentModel([
        understand([goal('query_config',{'key':'gift_multiplier'},'read'),
                    {**goal(),'id':'g2'}]),call('query_config',{'key':'gift_multiplier'}),finish([1]),finish([1])]))
    s=run(rt.start('查配置并发礼物',CTX))
    assert s['status']=='failed'


def test_unsupported_without_tool_is_honest_noncompletion(tmp_path):
    g=goal('',{},'unsupported')
    rt=WorkflowRuntime(tmp_path/'db',model=AgentModel([understand([g]),finish([],'unsupported')]))
    s=run(rt.start('给我充值钻石',CTX))
    assert s['status']=='failed' and s['stop_reason']=='no_evidence'
    assert s['result']['goals'][0]['status']=='unsupported'
    assert not rt.platform.actions.list_actions()
