import pytest
from scripts.evaluate_workflow import metrics, CASES

def test_metrics_keep_reliability_distinct_from_at_least_one_success():
    rows=[{'case_id':'a','passed':True,'first_tool_correct':True,'bad_args':0,'tool_calls':2,'steps':2,'duplicates':0,'recovery':True,'recovered':True,'tokens':10,'cost':None},
          {'case_id':'a','passed':False,'first_tool_correct':False,'bad_args':1,'tool_calls':2,'steps':2,'duplicates':1,'recovery':True,'recovered':False,'tokens':20,'cost':None}]
    m=metrics(rows)
    assert m['task_success_rate']==.5
    assert m['parameter_invalid_rate']==.25
    assert m['recovery_success_rate']==.5
    assert m['all_runs_pass_rate']==0
    assert m['at_least_one_pass_rate']==1
    assert m['mean_cost_usd'] is None
    assert m['duplicate_side_effects']==1

def test_eval_has_30_cases_and_required_distribution():
    from collections import Counter
    assert len(CASES)==30
    assert Counter(c['category'] for c in CASES)=={'normal':12,'ambiguity':8,'fault':6,'adversarial':4}

def test_remote_chain_oracle_requires_correct_query_after_write():
    from scripts.evaluate_model import chain_passed
    seed={'tool':'seed_test_data','args':{'table':'gifts','user_id':123,'gift_id':301,'quantity':10},'result':{'success':True,'data':{'batch_id':'b1','actual':10}}}
    query={'tool':'query_data','args':{'table':'gifts','batch_id':'b1'},'result':{'success':True,'data':{'total_quantity':10}}}
    state={'status':'completed','steps':[query,seed]}
    assert not chain_passed(state,10,0)
    state['steps']=[seed,query]
    assert chain_passed(state,10,0)
    state['steps'][1]={**query,'args':{'table':'gifts','batch_id':'wrong'}}
    assert not chain_passed(state,10,0)
