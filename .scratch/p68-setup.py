"""Prepare two real saved-session forks for the P68 physical UI check."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from agent_comms.comms import wire
from agent_comms.pi_vocabulary import HighThinkingLevel
from agent_comms.thread_management import ForkSpec
from agent_comms.thread_status import StoppedThreadStatus
from agent_comms.threads import Thread

base = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live')
base.mkdir(mode=0o700, parents=True, exist_ok=False)
original = wire()
seed = original.registry.require('p33-new-20261016-1627')
model = original.registry.require('forms-migration').model
source = Path(seed.session_file)
before = hashlib.sha256(source.read_bytes()).hexdigest()
copy = base / 'saved-session.jsonl'
shutil.copyfile(source, copy)
copy.chmod(0o600)
for key in ('AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID', 'AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE',
            'AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID',
            'PI_TASK', 'PI_PROMPT'):
    os.environ.pop(key, None)
os.environ['AGENT_COMMS_ROOT'] = str(base / 'root')
comms = wire(base / 'root')
root_id = comms.messaging.initialize_private_initial_protocol()
a = base / 'project-a'
b = base / 'project-b'
a.mkdir()
b.mkdir()
comms.registry.register(Thread('p68-seed', frozenset({'p68'}), str(a),
    session_file=str(copy), model=model, thinking_level=HighThinkingLevel), StoppedThreadStatus())
summary = {'owner': 'forms-migration', 'purpose': 'P68 two-thread reconnect and exit check',
           'root': str(comms.root), 'root_id': root_id, 'source': str(source),
           'source_sha256': before, 'model': model, 'threads': []}
(base / 'setup.json').write_text(json.dumps(summary, indent=2))
for name, project in (('p68-failed', a), ('p68-healthy', b)):
    thread = comms.threads.create(ForkSpec(name=name, parent='p68-seed', project=str(project),
        model=model, thinking_level=HighThinkingLevel, task=''))
    summary['threads'].append({'name': name, 'session_file': thread.session_file,
                               'pid': thread.pid, 'project': str(project)})
    (base / 'setup.json').write_text(json.dumps(summary, indent=2))
    print(name, thread.pid, flush=True)
summary['source_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == before
(base / 'setup.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
