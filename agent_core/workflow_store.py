"""SQLite task checkpoints, scoped result references, and process-safe resume locks."""
import fcntl
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from agent_core.action_store import ActionError, ActionStore, canonical, scope

from agent_core.workflow_state import migrate_state

class Budget(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    max_steps: int=Field(16,ge=1,le=100)
    max_tokens: int=Field(60000,ge=1,le=1000000)
    max_seconds: float=Field(120.0,gt=0,le=600)

class WorkflowStore:
    def __init__(self,path):
        self.db=ActionStore(path)
        self.lockdir=Path(str(path)+'.locks')
        self.lockdir.mkdir(parents=True,exist_ok=True)
        with self.db.connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS workflow_tasks (task_id TEXT PRIMARY KEY, scope TEXT NOT NULL, request_id TEXT, input TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(scope,request_id));
            CREATE TABLE IF NOT EXISTS workflow_refs (ref_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def lock(self,task_id):
        name=hashlib.sha256(task_id.encode()).hexdigest()
        with open(self.lockdir/name,'a') as handle:
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise ActionError('RESOURCE_BUSY','任务正在另一执行者运行')
            try: yield
            finally: fcntl.flock(handle,fcntl.LOCK_UN)

    def create(self,text,context,budget):
        owner=canonical(scope(context))
        request_id=context.get('request_id') or None
        with self.db.connection(write=True) as db:
            if request_id:
                row=db.execute('SELECT payload,input FROM workflow_tasks WHERE scope=? AND request_id=?',(owner,request_id)).fetchone()
                if row:
                    if row['input']!=text: raise ActionError('REQUEST_CONFLICT','请求 ID 对应不同任务')
                    return migrate_state(json.loads(row['payload']))
            state={'schema_version':1,'mode':'dry_run' if context.get('dry_run') else 'execute','task_id':str(uuid.uuid4()),'input':text,'scope':list(scope(context)), 'budget':budget.model_dump(),
                   'status':'ready','stop_reason':None,'steps':[],'trace':[],'pending':None,'replies':[],
                   'model_calls':0,'tool_calls':0,'tokens':0,'reported_tokens':0,'usage_complete':True,
                   'elapsed':0.0,'active_since':None,'bad_args':0,'created_at':time.time(),
                   'fault_id':context.get('fault_id'),'fault_remaining':context.get('fault_count'), 'result':None}
            db.execute('INSERT INTO workflow_tasks VALUES (?,?,?,?,?)',(state['task_id'],owner,request_id,text,canonical(state)))
            return state

    def get(self,task_id,context):
        with self.db.connection() as db: row=db.execute('SELECT scope,payload FROM workflow_tasks WHERE task_id=?',(task_id,)).fetchone()
        if not row: raise ActionError('TASK_NOT_FOUND','任务不存在')
        if row['scope']!=canonical(scope(context)): raise ActionError('SCOPE_MISMATCH','操作人、会话或环境不匹配')
        return migrate_state(json.loads(row['payload']))

    def save(self,state):
        with self.db.connection(write=True) as db:
            cur=db.execute('UPDATE workflow_tasks SET payload=? WHERE task_id=?',(canonical(state),state['task_id']))
            if cur.rowcount!=1: raise ActionError('TASK_NOT_FOUND','任务已被重置')

    def externalize(self,task_id,result):
        if len(canonical(result).encode())<=1500: return result
        rid=str(uuid.uuid4())
        data=result.get('data',{})
        rows=data.get('rows',[])
        with self.db.connection(write=True) as db:
            db.execute('INSERT INTO workflow_refs VALUES (?,?,?)',(rid,task_id,canonical(result)))
        return {**{k:v for k,v in result.items() if k!='data'},'data':{
            'ref_id':rid,'row_count':len(rows),'schema':list(rows[0]) if rows and isinstance(rows[0],dict) else [],
            'sample_3':rows[:3], **{k:v for k,v in data.items() if k in {'total_quantity','batch_id','actual','expected'}}}}

    def read_ref(self,task_id,args,context):
        self.get(task_id,context)
        with self.db.connection() as db: row=db.execute('SELECT task_id,payload FROM workflow_refs WHERE ref_id=?',(args['ref_id'],)).fetchone()
        if not row or row['task_id']!=task_id: raise ActionError('NOT_FOUND','引用不存在或不属于此任务')
        payload=json.loads(row['payload'])
        rows=payload.get('data',{}).get('rows')
        if rows is None: rows=[payload]
        start=args.get('offset',0); limit=args.get('limit',20)
        from agent_core.workflow_contracts import Ref, failure
        values = Ref(**args).model_dump()
        start, limit = values['offset'], values['limit']
        page = []
        def response():
            end = start + len(page)
            return {'success':True,'status':'success','code':'OK','data':{
                'rows':page,'row_count':len(rows),'offset':start,'returned_count':len(page),
                'next_offset':end if end < len(rows) else None,'truncated':end < len(rows)}}
        for item in rows[start:start+limit]:
            page.append(item)
            if len(canonical(response()).encode()) > 16384:
                page.pop()
                if not page:
                    return failure('ROW_TOO_LARGE','单行超过引用页大小限制，请查询更小字段集','read_ref')
                break
        return response()
