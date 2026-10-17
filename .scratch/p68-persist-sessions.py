"""Put this check's two newly created sessions in persistent owned storage."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil

from agent_comms.comms import wire
from agent_comms.launch_runtime import PACKAGE_ENV, ROOT_ID_ENV
from agent_comms.thread_status import StoppedThreadStatus

base = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live')
summary = json.loads((base / 'setup.json').read_text())
os.environ.update(AGENT_COMMS_ROOT=summary['root'], PI_CODING_AGENT_DIR=str(base / 'agent'))
os.environ[ROOT_ID_ENV] = summary['root_id']
os.environ[PACKAGE_ENV] = summary['native_package']
for key in ('AGENT_COMMS_AGENT_BIN', 'AGENT_COMMS_AGENT_ARGS', 'AGENT_COMMS_THREAD',
            'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID', 'PI_TASK', 'PI_WORKTREE', 'PI_PROMPT'):
    os.environ.pop(key, None)
comms = wire(Path(summary['root']))
store = base / 'sessions'
store.mkdir(exist_ok=False)
for item in summary['threads']:
    name = item['name']
    original = comms.registry.require(name)
    if original.session_file != item['session_file']:
        raise ValueError('Session changed before this check could persist it')
    comms.owners.stop(name)
    stopped = comms.registry.require(name)
    if stopped.process_alive:
        raise ValueError('Owned process has not stopped')
    old = Path(stopped.session_file)
    destination = store / (name + '.jsonl')
    shutil.copyfile(old, destination)
    destination.chmod(0o600)
    if hashlib.sha256(old.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
        raise ValueError('Session copy changed')
    comms.registry.register(replace(stopped, session_file=str(destination)), StoppedThreadStatus())
    item['old_owned_copy'] = str(old)
    item['session_file'] = str(destination)
    item['stopped_pid'] = item['pid']
    item['pid'] = None
    (base / 'setup.json').write_text(json.dumps(summary, indent=2))
for item in summary['threads']:
    result = comms.owners.start(item['name'])
    item['pid'] = result.pid
    (base / 'setup.json').write_text(json.dumps(summary, indent=2))
    print(item['name'], result.pid, flush=True)
print(json.dumps(summary, indent=2))
