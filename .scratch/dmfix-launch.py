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
name = ':262'
xvfb = type('X',(),{'pid':1076281})
display = XvfbDisplay(name)
env = dict(os.environ, DISPLAY=display.name)
for key in ('AGENT_COMMS_RUNTIME_ROOT', 'AGENT_COMMS_AGENT_BIN', 'AGENT_COMMS_AGENT_ARGS',
            'AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID',
            'PI_TASK', 'PI_WORKTREE', 'PI_PROMPT', 'NO_COLOR', 'TOAD_VALIDATION', 'PYTHONPATH'):
    env.pop(key, None)
runtime = Path('/home/ts/.local/share/agent-comms/runtimes/toad-1167674eb-core-9ed8e0560-native-6468a1979d983e9d-20261016T224432Z')
python = runtime / 'bin/python'
env.update(AGENT_COMMS_ROOT=setup['root'],
    AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=setup['root_id'],
    AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=setup['native_package'],
    PI_CODING_AGENT_DIR=str(base / 'agent'),
    AGENT_COMMS_NATIVE_CONFIG_DIR='/home/ts/.pi/agent',
    MENU_RUN='dmfix', PYTHONPATH='/home/ts/wt/toad-forms-migration/src:/home/ts/.cache/agent-scratch/claude-session/core-main/src',
    PYTHONDONTWRITEBYTECODE='1', XDG_STATE_HOME=str(base / 'state'),
    XDG_CONFIG_HOME=str(base / 'config'), XDG_DATA_HOME=str(base / 'data'))
initial_logs = sorted(str(p) for p in Path('/home/ts/.local/state/toad/logs').glob('*Terminal_crash*'))
log = (base / 'dmfix/terminal.log').open('w')
st = subprocess.Popen(['st', '-g', '160x48', '-e', str(python),
    '/home/ts/wt/toad-forms-migration/.scratch/menu3-entry.py', 'acp',
    f'{python} -m agent_comms.acp', str(base / 'project-a'),
    '--title', 'P68', '--session', 'p68-failed'], env=env, stdout=log, stderr=log,
    cwd='/home/ts/wt/toad-forms-migration')
frontend = psutil.Process(st.pid)
time.sleep(3)
windows = subprocess.check_output(['xdotool', 'search', '--pid', str(st.pid)], env=env, text=True)
window = int(windows.splitlines()[0])
info = {'owner': 'claude-session', 'purpose': 'P55 target menu wait',
        'display': name, 'xvfb_pid': xvfb.pid, 'st_pid': st.pid,
        'st_created': frontend.create_time(), 'window': window, 'runtime': str(runtime),
        'toad_source': 'installed b73e50199', 'core_source': 'installed 9ed8e0560',
        'default_crash_files_before': initial_logs}
(base / 'dmfix' / 'launch.json').write_text(json.dumps(info, indent=2))
subprocess.run(['import', '-window', str(window), str(base / 'dmfix' / 'startup.png')], env=env, check=True)
print(json.dumps(info, indent=2))
