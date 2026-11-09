"""30 deterministic engine scenarios with independent SQLite state oracles; no model fees."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path
from agent_core.action_store import ActionError
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_contracts import normalize

ROOT=Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'evals/workflow_cases.json').read_text())
CTX={'operator':'evaluation','session_id':'suite','env':'uat'}
SEED={'table':'gifts','user_id':123,'gift_id':301,'quantity':10}

def tool(name,args):return {'tool':name,'args':args}
class ScenarioModel:
    name='scripted_fixture'
    def __init__(self,decisions):self.decisions=iter(decisions)
    async def next(self,messages,context,max_tokens):
        decision=next(self.decisions,{'final':'fixture sequence complete'})
        decision=json.loads(json.dumps(decision))
        for key,value in decision.get('args',{}).items():
            if value in ('$batch','$change'):
                observations=[json.loads(m['content']) for m in messages if m['role']=='tool']
                field='batch_id' if value=='$batch' else 'action_id'
                decision['args'][key]=next(o['data'][field] for o in reversed(observations) if field in o.get('data',{}))
        return {**decision,'usage':{'total_tokens':0},'model':self.name,'prompt_version':'fixture-v1'}

def decisions(name):
    seed=tool('seed_test_data',SEED)
    script=tool('run_script',{'script_id':'send_gifts','user_id':123,'gift_id':301,'quantity':10})
    config=tool('update_config',{'key':'gift_multiplier','value':2})
    if name in {'seed','new_action','auth','transient','timeout','half','response_loss','restart','prod','tampered_approval','changed_scope','skip_approval'}:return [seed]
    if name=='seed_query':return [seed,tool('query_data',{'table':'gifts','batch_id':'$batch'})]
    if name=='script':return [script]
    if name=='script_query':return [script,tool('query_data',{'table':'script_runs','batch_id':'$batch'})]
    if name=='config_read':return [tool('query_config',{'key':'gift_multiplier'})]
    if name=='config_update':return [config,tool('query_config',{'key':'gift_multiplier'})]
    if name=='config_rollback':return [config,tool('rollback_config',{'change_id':'$change'})]
    if name=='cleanup':return [seed,tool('cleanup_data',{'batch_id':'$batch'})]
    if name=='scripts':return [tool('list_scripts',{})]
    if name=='empty_query':return [tool('query_data',{'table':'gifts'})]
    if name=='maintenance':return [tool('update_config',{'key':'maintenance_mode','value':True})]
    if name=='bad_args_repair':return [tool('seed_test_data',{**SEED,'quantity':'10'}),seed]
    if name=='invalid_table':return [tool('query_data',{'table':'users'}),tool('query_data',{'table':'orders'})]
    # Missing-parameter fixtures exercise persistence of the resulting clarification.
    return [tool('ask_clarification',{'question':name+': 请补充必要信息或明确候选'})]

def metrics(rows):
    n=len(rows)
    groups=defaultdict(list)
    for r in rows:groups[r['case_id']].append(r['passed'])
    recovery=[r for r in rows if r['recovery']]
    calls=sum(r['tool_calls'] for r in rows)
    successful=[r for r in rows if r['passed']]
    costs=[r['cost'] for r in rows]
    return {'task_success_rate':sum(r['passed'] for r in rows)/n if n else None,
            'tool_selection_accuracy':sum(r['first_tool_correct'] for r in rows)/n if n else None,
            'parameter_invalid_rate':sum(r['bad_args'] for r in rows)/calls if calls else 0,
            'mean_success_steps':sum(r['steps'] for r in successful)/len(successful) if successful else None,
            'duplicate_side_effects':sum(r['duplicates'] for r in rows),
            'recovery_success_rate':sum(r['recovered'] for r in recovery)/len(recovery) if recovery else None,
            'mean_tokens':sum(r['tokens'] for r in rows)/n if n else None,
            'mean_cost_usd':sum(costs)/n if n and all(c is not None for c in costs) else None,
            'all_runs_pass_rate':sum(all(g) for g in groups.values())/len(groups) if groups else None,
            'at_least_one_pass_rate':sum(any(g) for g in groups.values())/len(groups) if groups else None}

async def run_case(case,path):
    name=case['id'];ds=decisions(name);ctx=dict(CTX)
    if name=='prod':ctx['env']='prod'
    faults={'auth':'f_403','transient':'f_5xx','timeout':'f_timeout','half':'f_halfseed','response_loss':'f_response_loss'}
    if name in faults:ctx['fault_id']=faults[name]
    if name=='transient':ctx['fault_count']=1
    if name=='skip_approval':ctx.update(approved=True,execute_confirmed=True)
    from evals.environments.workflow import WorkflowEnvironment
    env=WorkflowEnvironment(path,model=ScenarioModel(ds))
    rt=env.runtime
    state=await env.apply({'op':'start','text':name,'context':ctx})
    rejected=False
    if name in {'tampered_approval','changed_scope'}:
        try:await rt.resume(state['task_id'],{**ctx,**({'operator':'intruder'} if name=='changed_scope' else {})},
                            action_id='wrong' if name=='tampered_approval' else state['pending']['action_id'],decision='approve')
        except ActionError:rejected=True
    elif name!='skip_approval':
        for _ in range(5):
            if state['status']!='approval_wait':break
            if name=='restart':rt=WorkflowRuntime(path,model=ScenarioModel([]),retry_delays=(0,0))
            # This harness approves only its own fixed fixture snapshots.
            p=state['pending'];normalize(p['tool'],p['args'])
            state=await rt.resume(state['task_id'],ctx,action_id=p['action_id'],decision='approve',confirm_effect='delete_batch' if p['tool']=='cleanup_data' else None,snapshot_hash=p.get('snapshot_hash'))
    if name=='new_action':
        rt=WorkflowRuntime(path,model=ScenarioModel(ds),retry_delays=(0,0))
        state=await rt.start(name,ctx)
        state=await rt.resume(state['task_id'],ctx,action_id=state['pending']['action_id'],decision='approve')
    # Independent oracle: raw database rows, not the assistant's success claims.
    with sqlite3.connect(path) as db:
        gifts=[json.loads(r[0]) for r in db.execute('SELECT payload FROM gifts')]
        configs={r[0]:json.loads(r[1]) for r in db.execute('SELECT key,value FROM workflow_config')}
        receipt_count=db.execute('SELECT count(*) FROM platform_receipts').fetchone()[0]
        checkpoints=[json.loads(r[0]) for r in db.execute('SELECT payload FROM workflow_tasks')]
        write_attempts=sum(s.get('attempts',0) for c in checkpoints for s in c['steps'] if s['tool'] in {'seed_test_data','run_script','update_config','cleanup_data','rollback_config'})
    actual=sum(g['quantity'] for g in gifts)
    passed=actual==case['expected_quantity'] and len(gifts)==case['expected_batches'] and state['status']==case['expected_status']
    if name=='config_update':passed &= configs.get('gift_multiplier')==2
    if name=='config_rollback':passed &= configs.get('gift_multiplier')==1
    if name=='maintenance':passed &= configs.get('maintenance_mode') is True
    if name in {'tampered_approval','changed_scope'}:passed &= rejected
    if name in {'seed_query','script_query'}:passed &= state['steps'][-1]['result']['data']['total_quantity']==10
    first=(state['steps'][0]['tool'] if state['steps'] else (state.get('pending') or {}).get('tool'))
    # Preparation may fail on policy before a step is created; trace the intended first decision separately.
    correct=first==case['expected_tool'] or (name=='prod' and state['stop_reason']=='auth')
    return {'case_id':name,'passed':bool(passed),'status':state['status'],'stop_reason':state['stop_reason'],
            'expected_quantity':case['expected_quantity'],'actual_quantity':actual,'receipt_count':receipt_count,'committed_actions':receipt_count,'write_attempts':write_attempts,
            'first_tool_correct':correct,'bad_args':state['bad_args'],'tool_calls':state['tool_calls'],
            'steps':len(state['steps']),'duplicates':max(0,len(gifts)-case['expected_batches']),
            'recovery':name in {'restart','response_loss','transient'},'recovered':bool(passed),
            'tokens':state['reported_tokens'],'cost':0}

async def evaluate(repeat=4):
    rows=[]
    with tempfile.TemporaryDirectory() as directory:
        for case in CASES:
            for trial in range(repeat):
                rows.append({**await run_case(case,Path(directory)/f"{case['id']}-{trial}.db"),'trial':trial+1})
    fingerprint=hashlib.sha256(json.dumps(CASES,sort_keys=True).encode()).hexdigest()
    return {'mode':'deterministic_engine','model':'scripted_fixture','case_set_hash':fingerprint,'case_count':len(CASES),'repeat':repeat,
            'passed':sum(r['passed'] for r in rows),'total':len(rows),'metrics':metrics(rows),
            'notes':['Tool selection here tests fixture routing, not LLM accuracy. See model_acceptance.json.',
                     'All-runs-pass measures stability; at-least-one-pass measures pass@k. They are not interchangeable.',
                     'No pre-change executable exists for these 30 cases; do not compare their rate to the older 9-case cohort.'], 'cases':rows}

def main():
    from evals.runner import main as unified_main
    return unified_main()
if __name__=='__main__':raise SystemExit(main())
