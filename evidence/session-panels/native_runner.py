import fcntl,json,os,pty,select,signal,struct,subprocess,termios,time
from pathlib import Path
root=Path.cwd(); master,slave=pty.openpty()
fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,120,0,0))
ready=root/'.artifacts/native-ready'
ready.unlink(missing_ok=True)
env=os.environ.copy();env.update(TERM='xterm-256color',TOAD_NATIVE='1',TOAD_NATIVE_READY=str(ready),TOAD_PANEL_TABS='16',TOAD_ARTIFACT_ROOT=str(root/'.artifacts'),TOAD_PANEL_RECEIPT=str(root/'evidence/session-panels/native16.json'))
proc=subprocess.Popen([str(root/'.venv/bin/python'),'tests/session_thread_panels_pilot.py'],stdin=slave,stdout=slave,stderr=slave,env=env,start_new_session=True)
os.close(slave); deadline=time.monotonic()+60; sent=False
with (root/'evidence/session-panels/native16.ansi').open('wb') as log:
    while proc.poll() is None and time.monotonic()<deadline:
        if ready.exists() and not sent:
            os.write(master,b'NATIVE');sent=True
        if select.select([master],[],[],.1)[0]:
            try:log.write(os.read(master,65536))
            except OSError:break
    if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    while select.select([master],[],[],0)[0]:
        try:log.write(os.read(master,65536))
        except OSError:break
os.close(master)
print(json.dumps({'exit_code':proc.returncode,'physical_pty_input_sent':sent}))
raise SystemExit(proc.returncode)
