"""One host: shared runtime access versus exclusive maintenance."""
import fcntl
from pathlib import Path
from contextlib import contextmanager
from agent_core.action_store import ActionError

@contextmanager
def maintenance_lock(path, exclusive=False):
    directory=Path(str(path)+'.locks');directory.mkdir(parents=True,exist_ok=True)
    with open(directory/'maintenance.lock','a') as handle:
        flag=fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try: fcntl.flock(handle,flag|fcntl.LOCK_NB)
        except BlockingIOError: raise ActionError('RESOURCE_BUSY','运行或维护中，不能重置状态')
        try: yield
        finally: fcntl.flock(handle,fcntl.LOCK_UN)
