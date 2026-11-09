"""Core import must not initialize optional graph or legacy platform clients."""
import os
from pathlib import Path
import subprocess
import sys


def test_workflow_api_import_without_optional_graph(tmp_path):
    root = str(Path(__file__).resolve().parents[1])
    program = '''
import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname in {'agent_core.langgraph_agent.graph', 'langgraph', 'langchain', 'pymysql', 'aiohttp'}:
   raise ImportError('core loaded optional dependency: '+fullname)
sys.meta_path.insert(0, Block())
from agent_core.workflow import WorkflowRuntime
from api.offline_server import create_app
assert any(r.path == '/workflows' for r in create_app().routes)
'''
    result = subprocess.run([sys.executable, '-c', program], cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': root}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
