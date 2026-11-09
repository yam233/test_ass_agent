"""Fixtures, seeded wrong decisions, and observation-checked trajectory replay."""
import copy
import hashlib
import json
import random
import re
from agent_core.action_store import canonical
from agent_core import workflow_model
from agent_core.workflow_contracts import catalog

UUID=re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',re.I)

def signature():
    return hashlib.sha256(canonical([workflow_model.SYSTEM,catalog()]).encode()).hexdigest()

class ReplayIncompatible(ValueError): pass

class IdMap:
    def __init__(self): self.ids={}
    def normalize(self,value):
        def sub(match):
            key=match.group(0)
            if key not in self.ids: self.ids[key]=f'@id{len(self.ids)}@'
            return self.ids[key]
        # Normalize embedded JSON strings as well as ordinary values.
        if isinstance(value,dict): return {k:self.normalize(v) for k,v in value.items()}
        if isinstance(value,list): return [self.normalize(v) for v in value]
        if isinstance(value,str):
            try:
                decoded=json.loads(value)
                if isinstance(decoded,(dict,list)): return canonical(self.normalize(decoded))
            except (ValueError,TypeError): pass
            return UUID.sub(sub,value)
        return value
    def restore(self,value):
        text=canonical(value)
        reverse={v:k for k,v in self.ids.items()}
        for symbol in re.findall(r'@id\d+@',text):
            if symbol not in reverse: raise ReplayIncompatible('录播输出引用了当前观察不存在的对象')
            text=text.replace(symbol,reverse[symbol])
        return json.loads(text)

class RecordingModel:
    def __init__(self,model): self.model=model;self.records=[];self.ids=IdMap();self.name=getattr(model,'name','recorded');self.llm=getattr(model,'llm',None)
    async def next(self,messages,context,max_tokens):
        observation=self.ids.normalize(messages)
        decision=await self.model.next(messages,context,max_tokens)
        self.records.append({'signature':signature(),'observation':observation,'output_cap':max_tokens,
                             'decision':self.ids.normalize(decision),'model':self.name})
        return decision

class ReplayModel:
    name='historical_replay'
    def __init__(self,records): self.records=iter(records);self.ids=IdMap()
    async def next(self,messages,context,max_tokens):
        row=next(self.records,None)
        if row is None or row['signature']!=signature() or row['observation']!=self.ids.normalize(messages) or row['output_cap']!=max_tokens:
            raise ReplayIncompatible('replay_incompatible: 提示词、观察或预算与录播不匹配')
        return {**self.ids.restore(row['decision']),'replay':True}

class ScriptModel:
    name='scripted_fixture'
    def __init__(self,decisions): self.decisions=iter(copy.deepcopy(decisions))
    async def next(self,messages,context,max_tokens):
        decision=next(self.decisions,{'final':'fixture done'})
        observations=[json.loads(m['content']) for m in messages if m['role']=='tool']
        for key,value in decision.get('args',{}).items():
            if isinstance(value,str) and value.startswith('$'):
                field='batch_id' if value=='$batch' else 'action_id'
                values=[o['data'][field] for o in observations if o.get('success') and field in o.get('data',{})]
                if not values: raise ValueError('fixture observation unavailable')
                decision['args'][key]=values[0] if value=='$first_change' else values[-1]
        return {**decision,'usage':{'total_tokens':0},'model':self.name}

class ChaosModel(ScriptModel):
    name='seeded_chaos'
    def __init__(self,seed,kind):
        rng=random.Random(seed)
        read={'tool':'query_data','args':{'table':'gifts'}}
        seed_call={'tool':'seed_test_data','args':{'table':'gifts','user_id':123,'gift_id':301,'quantity':10}}
        cases={'wrong_tool':[{'tool':'not_a_tool','args':{}}]*2,
               'missing_args':[{'tool':'seed_test_data','args':{'quantity':rng.randint(1,10)}}]*2,
               'repeat_read':[read,read], 'repeat_write':[seed_call,seed_call],
               'unauthorized':[seed_call], 'normal':[read], 'budget':[read]}
        super().__init__(cases[kind])
