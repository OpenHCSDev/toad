import fcntl,os,pty,select,struct,subprocess,sys,termios
from pathlib import Path
root=Path('.artifacts/crash').resolve();root.mkdir(exist_ok=True)
m,s=pty.openpty();fcntl.ioctl(s,termios.TIOCSWINSZ,struct.pack('HHHH',43,140,0,0))
p=subprocess.Popen([sys.executable,'-u','tests/terminal_crash_pilot.py',str(root)],stdin=s,stdout=s,stderr=s,env=dict(os.environ,TERM='xterm-256color'),start_new_session=True)
os.close(s);data=[]
while True:
 if select.select([m],[],[],.1)[0]:
  try:data.append(os.read(m,65536))
  except OSError:break
 elif p.poll() is not None:break
p.wait();os.close(m)
tape=b''.join(data).decode(errors='replace')
Path('.artifacts/terminal.txt').write_text(tape)
files=list((root/'state/toad/logs').glob('Terminal_crash*.txt'))
assert p.returncode==1,(p.returncode,tape[-2000:])
assert len(files)==1,files
body=files[0].read_text()
assert 'RecursionError: CONTROLLED_TERMINAL_CAPTURE_PROOF' in body
assert 'fail_after_paint' in body and 'Traceback' in body
assert files[0].stat().st_mode & 0o777 == 0o600
assert 'Terminal traceback saved:' in tape
assert 'CONTROLLED_TERMINAL_CAPTURE_PROOF' in tape
assert 'locals' not in body
print('PASS actual PTY terminal UI exception: exit1, printed error retained, persistent traceback names failing callback, one owner-only file, no locals')
