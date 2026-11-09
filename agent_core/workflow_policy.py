"""Local server-owned grants. Client restrictions can only narrow authority."""
import hashlib
import json
import os
from pathlib import Path
from agent_core.action_store import ActionError, canonical
from agent_core.workflow_contracts import SPECS, WRITES

DEFAULT_PATH = Path(__file__).resolve().parents[1]/'config/workflow_policy.json'


def require_write_context(context):
    if not isinstance(context.get('operator'), str) or not context['operator'].strip():
        raise ActionError('BAD_ARGS', '写操作需要显式 operator')
    if not isinstance(context.get('env') or context.get('environment'), str) or not (context.get('env') or context.get('environment')).strip():
        raise ActionError('BAD_ARGS', '写操作需要显式 env')
    if str(context.get('env') or context.get('environment')).lower() == 'prod':
        raise ActionError('PERMISSION_DENIED', '生产环境禁止写入')


def resolve_policy(context: dict, saved: dict | None = None) -> dict:
    policy = json.loads(Path(os.getenv('WORKFLOW_POLICY_PATH', DEFAULT_PATH)).read_text())
    grants = policy['operators'].get(context.get('operator'), [k for k,v in SPECS.items() if not v[1].startswith('write')])
    if not isinstance(grants, list) or any(t not in SPECS for t in grants):
        raise ActionError('POLICY_INVALID', '服务端工具授权无效')
    allowed = set(grants)
    restriction = context.get('allowed_tools')
    if restriction is not None:
        if not isinstance(restriction, list) or any(not isinstance(t,str) for t in restriction):
            raise ActionError('BAD_ARGS', 'allowed_tools 必须为字符串列表')
        allowed.intersection_update(restriction)
    if saved is not None:
        allowed.intersection_update(saved['allowed_tools'])
    threshold = policy.get('cleanup_max_quantity', 1000)
    if type(threshold) is not int or threshold < 0:
        raise ActionError('POLICY_INVALID', '清理阈值无效')
    if saved is not None: threshold=min(threshold,saved.get('cleanup_max_quantity',threshold))
    return {'allowed_tools':sorted(allowed),'cleanup_max_quantity':threshold,
            'policy_version':hashlib.sha256(canonical(policy).encode()).hexdigest(),
            'explicit_write':bool(context.get('operator') and (context.get('env') or context.get('environment'))) and (saved or {}).get('explicit_write',True)}


def check_tool(tool, context, saved=None):
    policy = resolve_policy(context, saved)
    if tool not in policy['allowed_tools']:
        raise ActionError('PERMISSION_DENIED', '服务端策略拒绝工具: '+tool)
    if tool in WRITES:
        require_write_context(context)
        if not policy['explicit_write']:
            raise ActionError('BAD_ARGS', '任务创建时缺少显式写入上下文，请重新创建任务')
    return policy


def snapshot_hash(action_id, tool, args, impact):
    return hashlib.sha256(canonical([action_id,tool,args,impact]).encode()).hexdigest()
