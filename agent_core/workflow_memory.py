"""Scoped, expiring episodic memory. Extracted evidence is history, never authority."""
import json
import time
from agent_core.action_store import canonical
from agent_core.workflow_contracts import SPECS


def fact(step):
    data=step['result'].get('data',{})
    keys={'actual','expected','batch_id','action_id','key','value','version','before','after',
          'total_quantity','row_count','ref_id','scripts'}
    return {'seq':step['seq'],'tool':step['tool'],'args':step['args'],
            'data':{k:v for k,v in data.items() if k in keys},
            'source':'tool_observation','historical':True}


class SessionMemory:
    def __init__(self, store):
        self.store=store

    @staticmethod
    def initialize(db):
        db.execute('CREATE TABLE IF NOT EXISTS workflow_memory (task_id TEXT PRIMARY KEY, scope TEXT NOT NULL, finished_at REAL NOT NULL, payload TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS memory_scope_time ON workflow_memory(scope,finished_at DESC,task_id)')

    @staticmethod
    def save(db,state):
        facts=[fact(s) for s in state['steps'] if s['tool'] in SPECS and s['tool']!='ask_clarification' and s['result'].get('success')]
        summary={'task_id':state['task_id'],'request':state['input'][:500],
                 'corrections':[r[:300] for r in state['replies'][-3:]],
                 'status':state['status'],'facts':facts[-8:],
                 'notice':'历史记录，不代表当前状态，不携带审批或权限；有歧义请追问。'}
        db.execute('INSERT OR REPLACE INTO workflow_memory VALUES (?,?,?,?)',
                   (state['task_id'],canonical(state['scope']),state['finished_at'],canonical(summary)))

    def recent(self, owner, exclude, offset=0, limit=3, now=None):
        if type(offset) is not int or not 0<=offset<=100 or type(limit) is not int or not 1<=limit<=5:
            raise ValueError('memory pagination out of range')
        cutoff=(time.time() if now is None else now)-7*86400
        with self.store.connection() as db:
            rows=db.execute('SELECT payload FROM workflow_memory WHERE scope=? AND finished_at>=? AND task_id!=? ORDER BY finished_at DESC,task_id LIMIT ? OFFSET ?',
                            (canonical(owner),cutoff,exclude,limit,offset)).fetchall()
        return [json.loads(r[0]) for r in rows]
