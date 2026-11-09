"""Export synthetic contracts and fixtures; no legacy platform data or secrets."""
import json
from pathlib import Path
from agent_core.workflow_contracts import catalog, normalize, failure

EXAMPLES={
 'list_scripts':{},'query_config':{'key':'gift_multiplier'},'query_data':{'table':'gifts'},
 'update_config':{'key':'gift_multiplier','value':2},
 'seed_test_data':{'table':'gifts','user_id':123,'gift_id':301,'quantity':10},
 'cleanup_data':{'batch_id':'example-batch'},'run_script':{'script_id':'send_gifts','user_id':123,'gift_id':301,'quantity':10},
 'ask_clarification':{'question':'需要发放几个？'},'rollback_config':{'change_id':'example-change'},
 'read_ref':{'ref_id':'example-ref','offset':0,'limit':3}}

def main():
    from api.offline_server import create_app
    Path('contracts').mkdir(exist_ok=True);Path('fixtures').mkdir(exist_ok=True)
    Path('contracts/tools.json').write_text(json.dumps({'version':'workflow-v1','source':'synthetic; not recovered production contracts','tools':catalog()},ensure_ascii=False,indent=2)+'\n')
    Path('contracts/http.openapi.json').write_text(json.dumps(create_app().openapi(),ensure_ascii=False,indent=2)+'\n')
    fixtures={name:{'valid_request':normalize(name,args),'extra_field_request':{**args,'unexpected':'rejected'},
                    'bad_args_response':failure('BAD_ARGS','参数不符合 schema',name),
                    'permission_response':failure('PERMISSION_DENIED','当前环境或工具无权限',name)} for name,args in EXAMPLES.items()}
    fixtures['query_data']['response_samples']=[{'rows':[],'row_count':0}, {'rows':[{'batch_id':'sample-1','quantity':10}],'row_count':1},
        {'rows':[{'batch_id':'sample-1','quantity':10},{'batch_id':'sample-2','quantity':5}],'row_count':2}, {'rows':'invalid_type'}]
    Path('fixtures/workflow.json').write_text(json.dumps({'source':'synthetic','cases':fixtures},ensure_ascii=False,indent=2)+'\n')
    print('Exported 10 tool schemas, HTTP OpenAPI and synthetic fixtures')

if __name__=='__main__':main()
