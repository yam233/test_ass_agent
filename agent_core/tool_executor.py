"""POSIX supervised synchronous tools. No live DB connection crosses a fork."""
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import signal
import tempfile
import time
from agent_core.workflow_contracts import failure

ISOLATED_FAULTS={'f_tool_hang','f_crash_before_receipt','f_crash_after_commit'}


def _child(operation, output, remaining, fault):
    # Also bounds an orphan if its supervising SDK process crashes.
    signal.signal(signal.SIGTERM,signal.SIG_DFL)
    signal.signal(signal.SIGALRM,signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL,max(.01,remaining+1))
    try:
        if fault=='f_tool_hang': time.sleep(200)
        if fault=='f_crash_before_receipt':
            from contextlib import contextmanager
            from agent_core.action_store import ActionStore
            original=ActionStore.connection
            @contextmanager
            def connection(self,*args,**kwargs):
                with original(self,*args,**kwargs) as db:
                    db.set_trace_callback(lambda sql: os._exit(86) if sql.startswith('INSERT INTO platform_receipts') else None)
                    yield db
            ActionStore.connection=connection
        result=operation()
        if fault=='f_crash_after_commit': os._exit(86)
        content=json.dumps(result,ensure_ascii=False)
        if len(content.encode())>8*1024*1024:
            result=failure('RESULT_TOO_LARGE','工具原始结果超过8 MiB限制')
            content=json.dumps(result)
        Path(output).write_text(content)
    except BaseException as exc:
        Path(output).write_text(json.dumps(failure('TOOL_ERROR','工具执行异常：'+type(exc).__name__)))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)


async def execute_tool(request: dict, deadline: float, operation=None, cancel_check=None) -> dict:
    if operation is None:
        def operation():
            from agent_core.workflow_platform import WorkflowPlatform
            return WorkflowPlatform(request['path']).execute(request['tool'],request['args'],request['context'])
    remaining=deadline-time.monotonic()
    if remaining<=0: return {**failure('TIMEOUT','工具期限已耗尽'),'hard_timeout':True}
    context=multiprocessing.get_context('fork')
    with tempfile.TemporaryDirectory(prefix='testops-tool-') as directory:
        output=Path(directory)/'result.json'
        child=context.Process(target=_child,args=(operation,str(output),remaining,request.get('fault_id')))
        child.start()
        reason=None
        try:
            while child.is_alive():
                if cancel_check and cancel_check(): reason='CANCELLED';break
                if time.monotonic()>=deadline: reason='TIMEOUT';break
                await asyncio.sleep(.01)
        except asyncio.CancelledError:
            reason='TIMEOUT'
            raise
        finally:
            if child.is_alive():
                child.terminate()
                # Reap before another executor can retry the same action.
                end=time.monotonic()+1
                while child.is_alive() and time.monotonic()<end: await asyncio.sleep(.01)
                if child.is_alive(): child.kill()
            child.join(timeout=1)
            if child.is_alive():
                raise RuntimeError('tool process could not be reaped')
        if reason:
            return {**failure(reason,'执行者已终止；写入需按回执对账'),'hard_timeout':reason=='TIMEOUT','executor_exited':True}
        if not output.exists():
            return {**failure('OUTCOME_UNKNOWN','工具执行者退出，需查询回执'),'executor_exited':True}
        return json.loads(output.read_text())
