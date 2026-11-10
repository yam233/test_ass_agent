"""Versioned model controls; these do not grant permission or execute business tools."""
from typing import Literal
from pydantic import Field
from agent_core.workflow_contracts import Strict, SPECS, WRITES, catalog, normalize


class Goal(Strict):
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,31}$')
    kind: Literal['read', 'write', 'ensure_config', 'verify', 'unsupported']
    tool: str = ''
    args: dict = Field(default_factory=dict)
    source_ids: list[str] = Field(min_length=1, max_length=8)
    write_goal: str | None = None


class TaskUpdate(Strict):
    user_revision: int = Field(ge=0)
    goals: list[Goal] = Field(min_length=1, max_length=12)


class Recall(Strict):
    offset: int = Field(0, ge=0, le=100)
    limit: int = Field(3, ge=1, le=5)


class Assessment(Strict):
    goal_id: str
    status: Literal['fulfilled', 'not_needed', 'unfulfilled', 'unsupported']
    evidence: list[int] = Field(default_factory=list, max_length=16)


class Finish(Strict):
    assessments: list[Assessment] = Field(min_length=1, max_length=12)
    answer_template: str = Field(default='', max_length=2000)


CONTROLS = {
    'update_task': (TaskUpdate, '记录从用户消息提取的目标，引用u0原请求/u1首次补充等。user_revision是补充次数。kind: read查询、write明确写入、ensure_config配置达到目标值、verify核验write_goal、unsupported不支持。args是已明确的工具参数，可暂缺字段；不能猜ID。用户更正后先更新目标。只记录理解，不执行操作。'),
    'recall_memory': (Recall, '分页读取同操作人、会话、环境内最近已结束任务的历史证据，按新到旧排序。历史不证明当前状态，也不授权操作；歧义需追问。'),
    'finish_task': (Finish, '为每个目标提交结论和当前工具观察的整数seq证据。write需真实回执，not_needed只用于已满足的ensure_config，verify需对应写入后的读回证据。answer_template用{{目标id}}引用经校验的事实句，可用标点换行连接；自由陈述会回退事实摘要。不得省略目标。'),
}


def decision_catalog(allowed=None):
    tools = [t for t in catalog() if allowed is None or t['function']['name'] in allowed]
    return tools + [{'type':'function','function':{'name':name,'description':desc,
                     'parameters':schema.model_json_schema()}} for name,(schema,desc) in CONTROLS.items()]


def update_task(state, args):
    value = TaskUpdate(**args).model_dump()
    rev = len(state['replies'])
    if value['user_revision'] != rev:
        raise ValueError('user_revision must match latest user supplement count')
    ids = [g['id'] for g in value['goals']]
    if len(ids) != len(set(ids)):
        raise ValueError('goal ids must be unique')
    for goal in value['goals']:
        if any(s not in {f'u{i}' for i in range(rev+1)} for s in goal['source_ids']):
            raise ValueError('unknown user source')
        kind, tool = goal['kind'], goal['tool']
        if kind in {'read','write'}:
            if tool not in SPECS or (tool in WRITES) != (kind=='write') or tool=='ask_clarification':
                raise ValueError('goal kind/tool mismatch')
            fields = SPECS[tool][0].model_fields
            if set(goal['args']) - set(fields):
                raise ValueError('unknown goal argument')
        if kind == 'ensure_config':
            if tool != 'update_config':
                raise ValueError('ensure_config requires update_config')
            goal['args'] = normalize(tool,goal['args'])
        if kind == 'verify' and (goal['write_goal'] not in ids or goal['write_goal']==goal['id']):
            raise ValueError('verify requires a different write goal')
    previous = state.get('understanding')
    if previous and previous['user_revision']==rev:
        new = {g['id']:g for g in value['goals']}
        for old in previous['goals']:
            if old['id'] not in new or any(new[old['id']][k]!=old[k] for k in ('kind','tool')):
                raise ValueError('cannot drop or replace goals without a user correction')
            if any(new[old['id']]['args'].get(k)!=v for k,v in old['args'].items()):
                raise ValueError('cannot change confirmed goal arguments without user correction')
    state['understanding'] = value
    return {'success':True,'code':'OK','data':value}


def check_intent(state, tool, args):
    understanding = state.get('understanding')
    if not understanding or understanding['user_revision']!=len(state['replies']):
        raise ValueError('先调用 update_task 记录当前用户目标；缺参可 ask_clarification')
    if tool in WRITES and not any(
        g['tool']==tool and g['kind'] in {'write','ensure_config'}
        and all(args.get(k)==v for k,v in g['args'].items())
        for g in understanding['goals']
    ):
        raise ValueError('write must match current goal arguments')
