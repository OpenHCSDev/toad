"""Launch one physical st window on its own display for P68."""
import json
import os
from pathlib import Path
import subprocess
import time

import psutil
from capture_live import XvfbDisplay

base = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live')
setup = json.loads((base / 'setup.json').read_text())
name = ':254'
if Path('/tmp/.X11-unix/X254').exists():
    raise ValueError('Chosen isolated display already exists')
xlog = (base / 'p55/xvfb.log').open('w')
xvfb = subprocess.Popen(['Xvfb', name, '-screen', '0', '1680x1080x24', '-nolisten', 'tcp'],
                        stdout=xlog, stderr=xlog)
time.sleep(1)
if xvfb.poll() is not None:
    raise RuntimeError('Owned Xvfb did not start')
display = XvfbDisplay(name)
env = dict(os.environ, DISPLAY=display.name)
for key in ('AGENT_COMMS_RUNTIME_ROOT', 'AGENT_COMMS_AGENT_BIN', 'AGENT_COMMS_AGENT_ARGS',
            'AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID',
            'PI_TASK', 'PI_WORKTREE', 'PI_PROMPT', 'NO_COLOR', 'TOAD_VALIDATION'):
    env.pop(key, None)
runtime = Path('/home/ts/.local/share/agent-comms/current').resolve()
python = runtime / 'bin/python'
env.update(AGENT_COMMS_ROOT=setup['root'],
    AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=setup['root_id'],
    AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=setup['native_package'],
    PI_CODING_AGENT_DIR=str(base / 'agent'),
    AGENT_COMMS_NATIVE_CONFIG_DIR='/home/ts/.pi/agent',
    PYTHONPATH='/home/ts/wt/toad-forms-migration/src:'
               '/home/ts/wt/core-p55-new-session/src',
    PYTHONDONTWRITEBYTECODE='1', XDG_STATE_HOME=str(base / 'state'),
    XDG_CONFIG_HOME=str(base / 'config'), XDG_DATA_HOME=str(base / 'data'))
initial_logs = sorted(str(p) for p in Path('/home/ts/.local/state/toad/logs').glob('*Terminal_crash*'))
log = (base / 'p55/terminal.log').open('w')
st = subprocess.Popen(['st', '-g', '160x48', '-e', str(python),
    '-m', 'toad', 'acp',
    f'{python} -m agent_comms.acp', str(base / 'project-b'),
    '--title', 'P55', '--session', 'p68-healthy'], env=env, stdout=log, stderr=log,
    cwd='/home/ts/wt/toad-forms-migration')
frontend = psutil.Process(st.pid)
time.sleep(3)
windows = subprocess.check_output(['xdotool', 'search', '--pid', str(st.pid)], env=env, text=True)
window = int(windows.splitlines()[0])
info = {'owner': 'claude-session', 'purpose': 'P55 new-session dialog check',
        'display': name, 'xvfb_pid': xvfb.pid, 'st_pid': st.pid,
        'st_created': frontend.create_time(), 'window': window, 'runtime': str(runtime),
        'toad_source': 'fix/p55-new-session-dialog worktree', 'core_source': '7f2c55cb0',
        'default_crash_files_before': initial_logs}
(base / 'p55' / 'launch.json').write_text(json.dumps(info, indent=2))
subprocess.run(['import', '-window', str(window), str(base / 'p55' / 'startup.png')], env=env, check=True)
print(json.dumps(info, indent=2))
