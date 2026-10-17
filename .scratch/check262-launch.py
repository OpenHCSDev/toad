"""Launch Toad in plain st on the existing isolated display :262: launch.py OUT ENTRY [overlay]."""
import json, os, subprocess, sys, time
from pathlib import Path

base = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live')
out, entry = base / sys.argv[1], sys.argv[2]
overlay = sys.argv[3] if len(sys.argv) > 3 else None
out.mkdir(exist_ok=True)
setup = json.loads((base / 'setup.json').read_text())
env = dict(os.environ, DISPLAY=':262')
for key in ('AGENT_COMMS_RUNTIME_ROOT', 'AGENT_COMMS_AGENT_BIN', 'AGENT_COMMS_AGENT_ARGS',
            'AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID',
            'PI_TASK', 'PI_WORKTREE', 'PI_PROMPT', 'NO_COLOR', 'TOAD_VALIDATION', 'PYTHONPATH'):
    env.pop(key, None)
runtime = Path('/home/ts/.local/share/agent-comms/runtimes/toad-1167674eb-core-9ed8e0560-native-6468a1979d983e9d-20261016T224432Z')
python = runtime / 'bin/python'
env.update(AGENT_COMMS_ROOT=setup['root'], AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=setup['root_id'],
    AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=setup['native_package'],
    PI_CODING_AGENT_DIR=str(base / 'agent'), AGENT_COMMS_NATIVE_CONFIG_DIR='/home/ts/.pi/agent',
    PYTHONDONTWRITEBYTECODE='1', XDG_STATE_HOME=str(base / 'state'),
    XDG_CONFIG_HOME=str(base / 'config'), XDG_DATA_HOME=str(base / 'data'))
if overlay:
    env['PYTHONPATH'] = '/home/ts/wt/toad-forms-migration/src:' + overlay
log = (out / 'terminal.log').open('w')
st = subprocess.Popen(['st', '-g', '160x48', '-e', str(python), entry, 'acp',
    f'{python} -m agent_comms.acp', str(base / 'project-a'), '--title', 'P68', '--session', 'p68-failed'],
    env=env, stdout=log, stderr=log, cwd='/home/ts/wt/toad-forms-migration')
time.sleep(3)
window = int(subprocess.check_output(['xdotool', 'search', '--pid', str(st.pid)], env=env, text=True).split()[0])
info = {'owner': 'claude-session', 'display': ':262', 'st_pid': st.pid, 'window': window,
        'runtime': str(runtime), 'overlay': overlay}
(out / 'launch.json').write_text(json.dumps(info, indent=2))
print(json.dumps(info))
