"""Explicit deterministic demo rules, never a fallback for remote failures."""
import json
import re
from agent_core.langgraph_agent.llm import DeepSeekLLM

class RuleModel:
    name='offline_rules'
    async def next(self,messages,context,max_tokens=512):
        user=' '.join(m.get('content','') for m in messages if m['role']=='user')
        observations=[json.loads(m['content']) for m in messages if m['role']=='tool']
        completed=[o for o in observations if o.get('success')]
        last=completed[-1] if completed else None
        usage={'total_tokens':0,'prompt_tokens':0,'completion_tokens':0}
        def tool(name,args): return {'tool':name,'args':args,'usage':usage,'model':self.name}
        def final(text): return {'final':text,'usage':usage,'model':self.name}
        if any(s in user for s in ('忽略权限','跳过审批','全表删除','DROP TABLE','drop table')):
            return tool('ask_clarification',{'question':'只能使用测试环境白名单工具，不能跳过审批；请明确允许的操作。'})
        if last:
            data=last.get('data',{})
            if data.get('batch_id') and 'expected' in data and any(w in user for w in ('查询','核验')):
                return tool('query_data',{'table':'gifts','batch_id':data['batch_id']})
            if 'total_quantity' in data: return final(f"查询核验：共 {data['total_quantity']} 个礼物。")
            return final('模拟操作已完成。')
        if '回滚' in user:
            m=re.search(r'change_id[=: ]+([\w-]+)',user)
            return tool('rollback_config',{'change_id':m.group(1)}) if m else tool('ask_clarification',{'question':'请提供需要回滚的 change_id。'})
        if '清理' in user:
            m=re.search(r'batch_id[=: ]+([\w-]+)',user)
            return tool('cleanup_data',{'batch_id':m.group(1)}) if m else tool('ask_clarification',{'question':'请提供需要清理的 batch_id。'})
        if '配置' in user:
            key=next((k for k in ('gift_multiplier','maintenance_mode') if k in user),None)
            if not key: return tool('ask_clarification',{'question':'配置 key 是 gift_multiplier 还是 maintenance_mode？'})
            if any(w in user for w in ('修改','设置','改成')):
                m=re.search(r'(?:为|成|=)\s*(\d+|true|false)',user,re.I)
                if not m: return tool('ask_clarification',{'question':'请给出配置的新值。'})
                value=m.group(1).lower()
                return tool('update_config',{'key':key,'value':value=='true' if value in {'true','false'} else int(value)})
            return tool('query_config',{'key':key})
        if '脚本' in user and any(w in user for w in ('列表','扫描','有哪些')): return tool('list_scripts',{})
        if '脚本' in user and any(w in user for w in ('执行','运行')):
            intent={'intent':'run_script','params':{'user_id':DeepSeekLLM.extract_named_value(user,'user_id'),
                'gift_id':DeepSeekLLM.extract_named_value(user,'gift_id'),'quantity':DeepSeekLLM.extract_named_value(user,'quantity')}}
        else:
            # Parse only the write clause so a later query does not override it.
            clause=re.split(r'然后|再查询|并查询|，|,',user)[0]
            intent=DeepSeekLLM.rule_based_intent(clause)
        name=intent.get('tool_name') or intent.get('intent'); args=intent.get('params',{})
        if name in {'add_gift_to_backpack','run_script'}:
            fields={k:args.get(k) for k in ('user_id','gift_id','quantity')}
            if fields['quantity'] is None: fields['quantity']=DeepSeekLLM.extract_named_value(user,'quantity')
            missing=[k for k,v in fields.items() if v is None]
            if missing: return tool('ask_clarification',{'question':'请补充：'+', '.join(missing)})
            return tool('run_script',{'script_id':'send_gifts',**fields}) if name=='run_script' else tool('seed_test_data',{'table':'gifts',**fields})
        if name in {'query_gift_records','query_script_runs'}:
            return tool('query_data',{'table':'gifts' if name=='query_gift_records' else 'script_runs',**args})
        return tool('ask_clarification',{'question':'请明确查询、发放测试礼物、修改配置或运行内置脚本，并提供必填参数。'})
