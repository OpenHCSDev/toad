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
if not Path('/tmp/.X11-unix/X262').exists():
    raise ValueError('reuse :262')
xvfb = type('X',(),{'pid':1076281})
display = XvfbDisplay(name)
env = dict(os.environ, DISPLAY=display.name)
for key in ('AGENT_COMMS_RUNTIME_ROOT', 'AGENT_COMMS_AGENT_BIN', 'AGENT_COMMS_AGENT_ARGS',
            'AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID',
            'PI_TASK', 'PI_WORKTREE', 'PI_PROMPT', 'NO_COLOR', 'TOAD_VALIDATION', 'PYTHONPATH',
            'AGENT_COMMS_ROOT', 'AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID', 'AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE'):
    env.pop(key, None)
runtime = Path('/home/ts/.local/share/agent-comms/runtimes/toad-b73e50199-core-9ed8e0560-native-6468a1979d983e9d-20261016T223633Z')
python = runtime / 'bin/python'
env.update(
    MENU_RUN='menu3',
    PYTHONDONTWRITEBYTECODE='1', XDG_STATE_HOME=str(base / 'menu3/state'),
    XDG_CONFIG_HOME=str(base / 'menu3/config'), XDG_DATA_HOME=str(base / 'menu3/data'))
initial_logs = sorted(str(p) for p in Path('/home/ts/.local/state/toad/logs').glob('*Terminal_crash*'))
log = (base / 'menu3/terminal.log').open('w')
st = subprocess.Popen(['st', '-g', '160x48', '-e', str(python),
    '/home/ts/wt/toad-forms-migration/.scratch/menu3-entry.py', 'acp',
    f'{python} -m agent_comms.acp', '/home/ts/.agent-comms',
    '--title', 'P55 menu probe', '--session', 'new-model-ui-2248'], env=env, stdout=log, stderr=log,
    cwd='/home/ts/.agent-comms')
frontend = psutil.Process(st.pid)
time.sleep(3)
windows = subprocess.check_output(['xdotool', 'search', '--pid', str(st.pid)], env=env, text=True)
window = int(windows.splitlines()[0])
info = {'owner': 'claude-session', 'purpose': 'P55 target menu wait, live bus, no input',
        'display': name, 'xvfb_pid': xvfb.pid, 'st_pid': st.pid,
        'st_created': frontend.create_time(), 'window': window, 'runtime': str(runtime),
        'toad_source': 'installed b73e50199', 'core_source': 'installed 9ed8e0560',
        'default_crash_files_before': initial_logs}
(base / 'menu3' / 'launch.json').write_text(json.dumps(info, indent=2))
subprocess.run(['import', '-window', str(window), str(base / 'menu3' / 'startup.png')], env=env, check=True)
print(json.dumps(info, indent=2))
