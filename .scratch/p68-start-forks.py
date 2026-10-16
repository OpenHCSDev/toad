"""Continue the P68 setup after supplying its own private-root package pins."""
import json
import os
from pathlib import Path

from agent_comms.active_route import read_active_route
from agent_comms.comms import wire
from agent_comms.launch_runtime import PACKAGE_ENV, ROOT_ID_ENV
from agent_comms.pi_vocabulary import HighThinkingLevel
from agent_comms.thread_management import ForkSpec

base = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live')
summary = json.loads((base / 'setup.json').read_text())
route = read_active_route()
summary['native_package'] = str(route.native_package)
for key in ('AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID',
            'PI_TASK', 'PI_PROMPT', 'PI_WORKTREE', 'AGENT_COMMS_AGENT_BIN',
            'AGENT_COMMS_AGENT_ARGS'):
    os.environ.pop(key, None)
os.environ['AGENT_COMMS_ROOT'] = summary['root']
os.environ[ROOT_ID_ENV] = summary['root_id']
os.environ[PACKAGE_ENV] = summary['native_package']
comms = wire(Path(summary['root']))
print('Existing names:', list(comms.registry.snapshot().threads), flush=True)
for name, directory in (('p68-failed', 'project-a'), ('p68-healthy', 'project-b')):
    if name in comms.registry.snapshot().threads:
        raise ValueError(f'{name} already exists; inspect its previous attempt instead of replaying it')
    thread = comms.threads.create(ForkSpec(name=name, parent='p68-seed',
        project=str(base / directory), model=summary['model'],
        thinking_level=HighThinkingLevel, task=''))
    summary['threads'].append({'name': name, 'session_file': thread.session_file,
                               'pid': thread.pid, 'project': str(base / directory)})
    (base / 'setup.json').write_text(json.dumps(summary, indent=2))
    print(name, thread.pid, flush=True)
print(json.dumps(summary, indent=2))
