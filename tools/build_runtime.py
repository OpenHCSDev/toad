#!/usr/bin/env python3
"""Build, qualify and publish a reviewed Toad/Core runtime.

Uses clean git exports and wheels, with dependencies owned by Toad's locked graph.
Native package verification belongs to Core's native_package module.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile

from performance.capture_live import XvfbDisplay


def run(*args: str | Path, cwd: Path | None = None) -> str:
    print("+ " + " ".join(map(str, args)), file=sys.stderr, flush=True)
    return subprocess.check_output(list(map(str, args)), cwd=cwd, text=True).strip()


def runtime_references(runtimes: list[Path]) -> dict[str, list[int]]:
    """Inspect every process as root; an unreadable live process forbids pruning."""
    references = {str(path): [] for path in runtimes}
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            state = (process / 'stat').read_bytes().rsplit(b')', 1)[1].split()
            identity = state[19]
            if state[0] == b'Z' or int(state[6]) & 0x00200000:
                continue  # Zombies and kernel threads hold no userspace runtime.
        except FileNotFoundError:
            continue
        contents = []
        errors = []
        for name in ('environ', 'cmdline', 'maps'):
            try:
                contents.append((process / name).read_bytes())
            except OSError as error:
                errors.append(error)
        for link in (process / 'cwd', process / 'exe'):
            try:
                contents.append(os.fsencode(link.readlink()))
            except OSError as error:
                errors.append(error)
        try:
            for descriptor in (process / 'fd').iterdir():
                try:
                    contents.append(os.fsencode(descriptor.readlink()))
                except FileNotFoundError:
                    pass  # A descriptor may close during the scan.
        except OSError as error:
            errors.append(error)
        try:
            state = (process / 'stat').read_bytes().rsplit(b')', 1)[1].split()
            after = state[19]
            if state[0] == b'Z':
                continue
        except FileNotFoundError:
            continue
        if identity != after:
            raise RuntimeError(f'Process identity changed during inspection: {process.name}')
        if errors:
            raise RuntimeError(f'Incomplete process inspection: {process.name}: {errors}')
        for path, pids in references.items():
            if any(os.fsencode(path) in value for value in contents):
                pids.append(int(process.name))
    return references


def prune_runtimes(current: Path, previous: Path, *, delete: bool) -> dict:
    """Keep the two published versions and every prefix still used by a process."""
    selected = current.resolve(strict=True)
    previous = previous.resolve(strict=True)
    directory = selected.parent
    if previous.parent != directory or not current.is_symlink():
        raise ValueError('Current and previous must be installed sibling runtimes')
    runtimes = sorted(directory.iterdir())
    if any(path.is_symlink() or not path.is_dir() for path in runtimes):
        raise ValueError('Runtime directory contains unexpected files or symlinks')
    references = runtime_references(runtimes)
    result = {'before': len(runtimes), 'current': str(selected), 'previous': str(previous),
              'kept_by_pid': {path: pids for path, pids in references.items() if pids},
              'deleted': []}
    if delete:
        for path in runtimes:
            if path in (selected, previous) or references[str(path)]:
                continue
            # Repeat immediately before deletion: a viewer may have started since
            # the inventory. A changed default invalidates this whole operation.
            if current.resolve(strict=True) != selected:
                raise RuntimeError('Default changed during runtime cleanup')
            borrowers = runtime_references([path])[str(path)]
            if borrowers:
                result['kept_by_pid'][str(path)] = borrowers
                continue
            shutil.rmtree(path)
            result['deleted'].append(str(path))
            print(f'Removed unused runtime {path}', file=sys.stderr, flush=True)
    result['after'] = len(list(directory.iterdir()))
    return result


def publish_runtime(publication_tools: Path, root: Path) -> None:
    """Use Core's publication owner, then retire older unused installations.

    Run with the qualified target Python inside the reviewed publication window.
    Native stopping/restarting remains with Core's existing cutover owner.
    """
    publisher = (publication_tools / 'publish_runtime.py').resolve(strict=True)
    sys.path.insert(0, str(publisher.parents[1]))
    from tools.publish_runtime import RuntimePublication

    publication = RuntimePublication.installed()
    record = json.loads((publication.runtime / 'build.json').read_text())
    if record['runtime'] != str(publication.runtime):
        raise ValueError('Build record does not describe the installed runtime')
    previous = publication.current.resolve(strict=True)
    if previous == publication.runtime:
        raise ValueError('Runtime is already current; do not repeat publication')
    publication.publish(root)
    print(f'Linked {publication.runtime}', flush=True)
    # Pass the actual prior pointer, not a build baseline or a persistent list.
    print(run(sys.executable, Path(__file__).resolve(), '--prune-runtimes',
              '--current', publication.current, '--previous', previous, '--delete'))


def installation_main() -> None:
    parser = argparse.ArgumentParser(description='Publish or prune qualified runtimes')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--prune-runtimes', action='store_true')
    actions.add_argument('--publish-runtime', action='store_true')
    parser.add_argument('--current', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--delete', action='store_true')
    parser.add_argument('--publication-tools', type=Path, help="Core checkout's tools directory")
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if args.prune_runtimes:
        if args.current is None or args.previous is None:
            parser.error('--prune-runtimes requires --current and --previous')
        print(json.dumps(prune_runtimes(args.current, args.previous, delete=args.delete), indent=2))
    else:
        if args.publication_tools is None or args.root is None:
            parser.error('--publish-runtime requires --publication-tools and --root')
        publish_runtime(args.publication_tools, args.root)


def inventory() -> dict:
    return {
        d.metadata['Name'].lower().replace('_', '-'): {
            'version': d.version,
            'source': json.loads(d.read_text('direct_url.json') or 'null'),
        }
        for d in importlib.metadata.distributions()
    }


def read_inventory(python: Path) -> dict:
    return json.loads(run(python, Path(__file__).resolve(), '--inventory'))


class BuildDisplay(XvfbDisplay):
    """Own the isolated display created for qualification."""

    def __init__(self, output):
        self.log = (output / 'xvfb.log').open('w')
        self.server = subprocess.Popen(
            ['Xvfb', '-displayfd', '1', '-screen', '0', '1600x1000x24', '-nolisten', 'tcp'],
            stdout=subprocess.PIPE, stderr=self.log)
        try:
            super().__init__(':' + self.server.stdout.readline().decode().strip())
        except BaseException:
            self.server.terminate()
            self.server.wait(timeout=5)
            self.log.close()
            raise

    def __exit__(self, *exception):
        try:
            return super().__exit__(*exception)
        finally:
            self.server.terminate()
            self.server.wait(timeout=5)
            self.log.close()


class TerminalApp:
    """Own one isolated st/tmux lifetime, terminal observations and physical input."""

    columns, rows = 140, 40

    def __init__(self, command, display, output, environment, cwd):
        self.command, self.display, self.output = command, display, output
        self.environment = dict(environment, DISPLAY=display.name)
        self.cwd = cwd
        self.socket = output.parents[1] / f'mux-{os.getpid()}-{output.name}.sock'

    def mux(self, *arguments):
        return subprocess.run(['tmux', '-S', str(self.socket), *arguments],
                              env=self.environment, capture_output=True, text=True, timeout=5)

    def __enter__(self):
        import psutil
        self.output.mkdir(parents=True, exist_ok=True)
        self.log = (self.output / 'st.log').open('w')
        self.terminal = subprocess.Popen(
            ['st', '-g', f'{self.columns}x{self.rows}', '-e', 'tmux', '-S', str(self.socket),
             'new-session', '-s', 'qualify', '-x', str(self.columns), '-y', str(self.rows),
             shlex.join(list(map(str, self.command)))],
            cwd=self.cwd, env=self.environment, stdout=self.log, stderr=self.log)
        self.owner = psutil.Process(self.terminal.pid)
        self.created = self.owner.create_time()
        try:
            self.wait('terminal', lambda text: bool(text.strip()))
            self.mux('set-option', '-t', 'qualify', 'status', 'off').check_returncode()
            self.window = int(subprocess.check_output(
                ['xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(self.terminal.pid)],
                env=self.environment, text=True, timeout=10).splitlines()[0])
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def capture(self):
        result = self.mux('capture-pane', '-p', '-t', 'qualify:0.0')
        return result.stdout if result.returncode == 0 else ''

    def screenshot(self, name):
        path = self.output / f'{name}.png'
        run('import', '-display', self.display.name, '-window', 'root', path)
        return path

    def wait(self, name, predicate, seconds=40):
        deadline = time.monotonic() + seconds
        while True:
            text = self.capture()
            if predicate(text):
                (self.output / f'{name}.txt').write_text(text)
                return text
            if self.terminal.poll() is not None or time.monotonic() >= deadline:
                (self.output / f'{name}-failed.txt').write_text(text)
                self.screenshot(f'{name}-failed')
                raise RuntimeError(f'Terminal probe {name} failed; see {self.output}')
            time.sleep(.2)

    def keys(self, *keys):
        self.mux('send-keys', '-t', 'qualify:0.0', *keys).check_returncode()

    def click(self, label):
        text = self.wait('find-' + label.replace('/', '-'), lambda text: label in text)
        row, line = next((row, line) for row, line in enumerate(text.splitlines()) if label in line)
        self.click_cell(line.index(label) + len(label) // 2, row)

    def click_cell(self, column, row):
        geometry = subprocess.check_output(
            ['xdotool', 'getwindowgeometry', '--shell', str(self.window)],
            env=self.environment, text=True)
        size = dict(line.split('=', 1) for line in geometry.splitlines() if '=' in line)
        x = 2 + int((column + .5) * (int(size['WIDTH']) - 4) / self.columns)
        y = 2 + int((row + .5) * (int(size['HEIGHT']) - 4) / self.rows)
        XvfbDisplay.input(self.owner, self.created, self.window, 'mousemove', '--window',
                          str(self.window), str(x), str(y), 'click', '1')

    def __exit__(self, *exception):
        try:
            if self.terminal.poll() is None:
                self.mux('send-keys', '-t', 'qualify:0.0', 'C-q')
                try:
                    self.terminal.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.terminal.terminate()
                    self.terminal.wait(timeout=5)
        finally:
            self.mux('kill-server')
            self.log.close()


def check_startup(runtime: Path, output: Path, baseline: Path, thread: str) -> dict:
    """Import the built family, then read welcome, history and channels as a user."""
    output.mkdir()
    python = runtime / 'bin/python'
    modules = json.loads(run(python, '-I', '-B', '-c', '''
import importlib,json,toad
from pathlib import Path
root=Path(toad.__file__).parent
names=[]
for path in sorted(root.rglob('*.py')):
    parts=path.relative_to(root).with_suffix('').parts
    if parts[-1]=='__init__': parts=parts[:-1]
    name='.'.join(('toad',*parts));importlib.import_module(name);names.append(name)
print(json.dumps(names))
'''))
    (output / 'imports.json').write_text(json.dumps(modules, indent=2))
    home = output / 'home'
    home.mkdir(mode=0o700)
    saved = json.loads(run(baseline / 'bin/python', '-I', '-B', '-c', '''
import json,sys,os
from agent_comms.active_route import read_active_route
from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.launch_runtime import RestartEnvironment
c=wire(read_active_route());t=c.registry.require(sys.argv[1])
print(json.dumps(dict(path=str(t.runtime.path),backend=FieldCodec.encode(t.backend),model=t.model,
                     package=str(read_active_route().native_package),
                     config=str(RestartEnvironment.inherit(os.environ).native_config))))
''', thread))
    project = output / 'project'
    project.mkdir(mode=0o700)
    with Path(saved['path']).open('rb') as stream:
        captured = stream.read(os.fstat(stream.fileno()).st_size)
    captured = captured[:captured.rfind(b'\n') + 1]
    if not captured:
        raise ValueError('Startup requires nonempty saved history')
    source = project / 'saved.jsonl'
    source.write_bytes(captured)
    source.chmod(0o600)
    (output / 'saved-source.json').write_text(json.dumps(saved, indent=2))
    pointer = home / '.local/share/agent-comms/current'
    pointer.parent.mkdir(parents=True)
    pointer.symlink_to(runtime)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('AGENT_COMMS_', 'PI_', 'XDG_'))
                   and k not in ('PYTHONPATH', 'PYTHONHOME', 'NO_COLOR', 'TOAD_VALIDATION')}
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                       XDG_STATE_HOME=str(home / 'state'), XDG_DATA_HOME=str(home / 'data'),
                       AGENT_COMMS_ROOT=str(output / 'wire'))
    launch = subprocess.check_output([str(python), '-I', '-B', '-c', '''
import sys,json
from pathlib import Path
from agent_comms.comms import wire
from agent_comms.coordinator import Coordination
from agent_comms.agent_backend import AgentBackend
from agent_comms.field_codec import FieldCodec
from agent_comms.launch_runtime import RestartEnvironment
from agent_comms.native_package import pinned_native_package
c=wire();root_id=c.messaging.initialize_private_initial_protocol()
c.registry.declare(c.registry.new_thread('startup-saved',frozenset(),sys.argv[1],session_file=sys.argv[2],
    backend=FieldCodec.decode(type[AgentBackend],sys.argv[3]),model=json.loads(sys.argv[5])))
with Coordination(str(c.root/'coordination.sqlite3')) as store:store.install_private_runtime()
print(json.dumps(RestartEnvironment(root=str(c.root),root_id=root_id,package=str(pinned_native_package()),
    native_config=Path(sys.argv[4]),agent_directory=Path.home()/'pi').encode()))
''', str(project), str(source), saved['backend'], saved['config'], json.dumps(saved['model'])],
        env=environment, text=True)
    environment.update(json.loads(launch))
    with BuildDisplay(output) as display:
        command = [runtime / 'bin/toad']
        with TerminalApp(command, display, output / 'plain', environment, home) as app:
            app.wait('store', lambda text: 'Toad' in text or 'agent' in text.lower())
            app.screenshot('store')
        command += ['acp', f'{python} -I -B -m agent_comms.acp', str(home)]
        with TerminalApp(command, display, output / 'welcome', environment, home) as app:
            app.wait('welcome', lambda text: 'startup-saved' in text)
            app.screenshot('welcome')
            app.click('startup-saved')
            app.wait('saved', lambda text: 'User messages' in text and 'startup-saved' in text)
            app.screenshot('saved')
            app.click('Channels')
            app.click('#any')
            app.wait('any', lambda text: 'Message #any' in text)
            app.screenshot('any')
            check_filtered_return(app)
    result = dict(import_count=len(modules), plain='passed', welcome='passed', saved='passed',
                  channel='passed', filtered_return='passed', evidence=str(output))
    (output / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def check_filtered_return(app: TerminalApp) -> None:
    """Choose user-only checkboxes, PageUp and compare the visible returned rows."""
    app.keys('Escape')
    app.wait('saved-return', lambda text: 'User messages' in text)
    for label in ('Agent messages', 'Messages in', 'Messages out', 'Thinking', 'Tool calls', 'Other / notices'):
        app.click(label)
    app.click_cell(app.columns // 2, app.rows - 5)
    initial = app.capture().splitlines()[4:-8]
    app.keys('PPage', 'PPage', 'PPage')
    app.wait('page-up-moved', lambda text: text.splitlines()[4:-8] != initial)
    before = app.wait('filtered-before', lambda text: 'User messages' in text)
    time.sleep(.5)
    before = app.capture()
    (app.output / 'filtered-before.txt').write_text(before)
    app.screenshot('filtered-before')
    app.click('Channels')
    app.click('#any')
    app.wait('filtered-away', lambda text: 'Message #any' in text)
    app.keys('Escape')
    # Ignore the tab bar and animated footer; compare the actual message rows.
    expected = before.splitlines()[4:-4]
    app.wait('filtered-return', lambda text: text.splitlines()[4:-4] == expected)
    app.screenshot('filtered-return')


def open_saved_thread(runtime: Path, thread: str, display: XvfbDisplay, output: Path) -> Path:
    """Open our own terminal and observe the requested thread without app internals."""
    environment = dict(os.environ, AGENT_COMMS_RUNTIME_ROOT=str(runtime / 'bin'),
                       AGENT_COMMS_AGENT_BIN='pi')
    for name in ('NO_COLOR', 'TOAD_VALIDATION'):
        environment.pop(name, None)
    with TerminalApp(['toad-comms', thread], display, output / 'saved', environment, Path.home()) as app:
        app.wait('saved-thread', lambda text: thread in text and 'User messages' in text)
        return app.screenshot('saved-thread')






def check_message_wake(runtime: Path, output: Path, startup: Path) -> dict:
    """Deliver one new message to a fresh private SDK fork and require its reply."""
    output.mkdir(mode=0o700)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('AGENT_COMMS_', 'PI_', 'XDG_'))
                   and k not in ('PYTHONPATH', 'PYTHONHOME')}
    with (output / 'wake.log').open('w') as log:
        subprocess.run([str(runtime / 'bin/python'), '-I', '-B', '-c', '''
import asyncio,hashlib,json,os,sys,time
from pathlib import Path
from agent_comms.active_route import ActiveRoute,active_route_path
from agent_comms.comms import wire,Comms
from agent_comms.thread_status import StoppedThreadStatus
from agent_comms.agent_backend import AgentBackend
from agent_comms.field_codec import FieldCodec
from agent_comms.launch_runtime import LaunchRuntime
from agent_comms.wire_record import WireRecord
out, startup, runtime=map(Path,sys.argv[1:])
saved=json.loads((startup/'saved-source.json').read_text())
source=startup/'project/saved.jsonl'; digest=hashlib.sha256(source.read_bytes()).hexdigest()
home=out/'home';home.mkdir(mode=0o700)
pointer=home/'.local/share/agent-comms/current';pointer.parent.mkdir(parents=True);pointer.symlink_to(runtime)
os.environ.update(HOME=str(home), PI_CODING_AGENT_DIR=str(out/'pi'),
                  AGENT_COMMS_NATIVE_CONFIG_DIR=saved['config'])
for kind in ('CONFIG','DATA','STATE','CACHE'):os.environ['XDG_'+kind+'_HOME']=str(out/kind.lower())
c=Comms(out/'wire');root_id=c.messaging.initialize_private_initial_protocol()
route=ActiveRoute(c.root,root_id,Path(saved['package']))
path=active_route_path();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
path.write_text(json.dumps(FieldCodec.encode(route)));path.chmod(0o600)
os.environ.update(AGENT_COMMS_ROOT=str(c.root),AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
    AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=saved['package'],AGENT_COMMS_AGENT_BIN=str(runtime/'bin/pi-comms-native'))
c=wire(route)
parent=c.registry.declare(c.registry.new_thread('build-parent',frozenset(),str(out),session_file=str(source),
    backend=FieldCodec.decode(type[AgentBackend],saved['backend']),model=saved['model']),StoppedThreadStatus())
async def fork():return await parent.backend.fork(parent,str(runtime/'bin/pi-comms-native'),LaunchRuntime.running())
forked=asyncio.run(fork())
child=c.registry.declare(c.registry.new_thread('build-wake',frozenset(),str(out),parent=parent.name,
    session_file=forked.path,backend=parent.backend,model=parent.model),StoppedThreadStatus())
c.registry.declare(c.registry.new_thread('build-sender',frozenset(),str(out)),StoppedThreadStatus())
os.environ['PI_CODING_AGENT_DIR']=saved['config']
c.owners.start(child.name,agent_bin=str(runtime/'bin/pi-comms-native'),agent_args=())
try:
    sent=c.messaging.send_message('build-sender',child.name,'Reply with BUILD_WAKE followed immediately by _OK. Do not use tools.')
    deadline=time.monotonic()+120
    while True:
        failures=list((c.root/'diagnostics').glob('drain-*.json'))
        if failures:raise RuntimeError(f'Private wake produced a drain diagnostic: {failures}')
        messages=[m for line in c.bus.log.path.read_text().splitlines()
                  for m in WireRecord.public_from_wire(json.loads(line)).messages()]
        replies=[m for m in messages if m.sender==child.name and m.target=='build-sender' and 'BUILD_WAKE_OK' in m.body]
        current=c.registry.require(child.name)
        if replies and current.active_turn is None:break
        if time.monotonic()>deadline:raise TimeoutError('Private message did not complete its wake')
        time.sleep(.25)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    (out/'result.json').write_text(json.dumps(dict(completed=True,reply=replies[-1].body,
        session=forked.path,original_unchanged=True,drain_diagnostics=0)))
finally:
    c.owners.stop(child.name)
''', str(output), str(startup), str(runtime)], env=environment, stdout=log, stderr=log, check=True)
    result = json.loads((output / 'result.json').read_text())
    environment.update(HOME=str(output / 'home'), AGENT_COMMS_ROOT=str(output / 'wire'))
    for kind in ('CONFIG', 'DATA', 'STATE', 'CACHE'):
        environment['XDG_' + kind + '_HOME'] = str(output / kind.lower())
    with BuildDisplay(output) as display:
        command = [runtime / 'bin/toad', 'acp',
                   f'{runtime / "bin/python"} -I -B -m agent_comms.acp',
                   str(output), '--session', 'build-parent']
        with TerminalApp(command, display, output / 'reply', environment, output) as app:
            app.wait('parent', lambda text: 'User messages' in text)
            app.click('Channels')
            app.click('#any')
            app.wait('reply', lambda text: 'Message #any' in text and 'BUILD_WAKE_OK' in text)
            app.screenshot('reply')
    return result











@dataclass(frozen=True)
class GitExport:
    repository: Path
    revision: str
    label: str
    package_name: str

    @property
    def commit(self) -> str:
        return run('git', '-C', self.repository, 'rev-parse', self.revision + '^{commit}')

    def wheel(self, commit: str, exports: Path, cache: Path) -> Path:
        source = exports / self.label
        source.mkdir()
        # Streaming the archive avoids retaining another source copy in memory.
        with subprocess.Popen(
            ['git', '-C', str(self.repository), 'archive', commit], stdout=subprocess.PIPE
        ) as archive:
            subprocess.run(['tar', '-x', '-C', str(source)], stdin=archive.stdout, check=True)
            archive.stdout.close()
            if archive.wait():
                raise RuntimeError(f'git archive failed for {self.label}')
        wheels = cache / f'{self.label}-{commit}'
        if not wheels.exists():
            run('uv', 'build', '--wheel', '--out-dir', wheels, source)
        return self.only_wheel(wheels)

    def verify_wheel(self, wheel: Path, installed: dict) -> None:
        # Hatch owns static/dynamic versions; this export owns its package identity.
        with zipfile.ZipFile(wheel) as archive:
            metadata_path, = (name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
            metadata = message_from_bytes(archive.read(metadata_path))
        name = metadata['Name'].lower().replace('_', '-')
        if name != self.package_name or installed[name]['version'] != metadata['Version']:
            raise RuntimeError(f'{self.package_name} differs from its clean-export wheel')
        if installed[name]['source']['url'] != wheel.resolve().as_uri():
            raise RuntimeError(f'{self.package_name} was installed from a different wheel')

    @staticmethod
    def only_wheel(directory: Path) -> Path:
        wheel, = directory.glob('*.whl')
        return wheel


@dataclass(frozen=True)
class RuntimeBuild:
    toad: GitExport
    core: GitExport
    baseline: Path
    scratch: Path
    runtimes: Path
    thread: str
    start_env: Path | None

    def start_acceptance_thread(self, runtime: Path) -> bool:
        if self.start_env is None:
            return False
        environment = dict(os.environ)
        for entry in self.start_env.read_text().split():
            name, separator, value = entry.partition('=')
            if not separator or not name.isidentifier():
                raise ValueError(f'Invalid environment entry in {self.start_env}')
            environment[name] = value
        environment['PATH'] = f'{runtime / "bin"}:{environment["PATH"]}'
        environment['AGENT_COMMS_AGENT_BIN'] = str(runtime / 'bin/pi-comms-native')
        command = [runtime / 'bin/agent-comms', 'start', '--name', self.thread]
        print('+ ' + ' '.join(map(str, command)), file=sys.stderr, flush=True)
        started = subprocess.run(
            list(map(str, command)), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if started.returncode:
            raise RuntimeError(
                f'AcceptanceThreadStartFailed: {self.thread}: {started.stdout.strip()}'
            )
        result = json.loads(started.stdout)
        if result.get('launched') is not True:
            raise RuntimeError(
                f'AcceptanceThreadAlreadyRunning: {self.thread}; stop it before '
                'using --start-thread'
            )
        return True

    def build(self) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.runtimes.mkdir(parents=True, exist_ok=True)
        toad_commit, core_commit = self.toad.commit, self.core.commit
        manifest = subprocess.check_output([
            'git', '-C', str(self.core.repository), 'show', f'{core_commit}:stack/pi-native.sha256'
        ])
        native_pin = hashlib.sha256(manifest).hexdigest()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        destination = self.runtimes / f'toad-{toad_commit[:9]}-core-{core_commit[:9]}-native-{native_pin[:16]}-{stamp}'
        cache = self.scratch / 'wheels'
        with tempfile.TemporaryDirectory(prefix='export-', dir=self.scratch) as temporary, ExitStack() as cleanup:
            exports = Path(temporary)
            toad_wheel = self.toad.wheel(toad_commit, exports, cache)
            core_wheel = self.core.wheel(core_commit, exports, cache)
            requirements = exports / 'requirements.txt'
            run(
                'uv', 'export', '--frozen', '--no-dev', '--no-header', '--no-annotate',
                '--no-emit-package', self.toad.package_name,
                '--no-emit-package', self.core.package_name,
                '--output-file', requirements,
                cwd=exports / self.toad.label,
            )
            # Atomic acquisition: an existing/borrowed prefix never enters cleanup.
            destination.mkdir()
            cleanup.callback(shutil.rmtree, destination)
            run('uv', 'venv', '--allow-existing', '--python', (self.baseline / 'bin/python').resolve(), destination)
            python = destination / 'bin/python'
            # The clean Toad lock owns the complete dependency set; the two reviewed
            # source exports replace only their own packages.
            run('uv', 'pip', 'install', '--python', python, '--no-deps', '-r', requirements, toad_wheel, core_wheel)
            core_package = Path(run(python, '-c', 'import agent_comms; print(agent_comms.__path__[0])'))
            if (core_package / 'package-lock.json').is_file():
                run('npm', 'ci', '--ignore-scripts', '--omit=dev', cwd=core_package)
            run('uv', 'pip', 'check', '--python', python)
            # Locate through Core, not an assumed interpreter/version layout.
            resources = Path(run(python, '-c', 'from agent_comms.native_package import MANIFEST; print(MANIFEST.parent)'))
            if (resources / 'pi-native.sha256').read_bytes() != manifest:
                raise RuntimeError('Installed Core native pin differs from the clean export')
            native_relative = Path(f'.pi-native-{native_pin[:16]}/node_modules/@earendil-works/pi-coding-agent')
            native_source = self.core.repository / 'stack' / native_relative
            run(python, '-I', '-B', '-c',
                'import sys; from pathlib import Path; from agent_comms.native_package import verify_native_package; '
                'verify_native_package(Path(sys.argv[1]))', native_source)
            if any(path.stat().st_mode & 0o222 for path in native_source.rglob('*') if path.is_file()):
                raise ValueError('Shared native package files must be immutable')
            shutil.copytree(native_source, resources / native_relative, copy_function=os.link)
            run(destination / 'bin/toad', '--version')
            run(python, '-c', 'import toad.cli, agent_comms.cli, textual, formbridge, objectstate')
            # Keep an installed but unqualified candidate available for diagnosis.
            # Only build.json below certifies readiness; never rebuild to inspect it.
            cleanup.pop_all()
        return self.qualify(destination)

    def qualify(self, destination: Path) -> Path:
        """Finish the existing readiness checks on an installed candidate."""
        if (destination / 'build.json').exists():
            raise ValueError('Runtime is already qualified')
        toad_commit, core_commit = self.toad.commit, self.core.commit
        installed = read_inventory(destination / 'bin/python')
        for export, commit in ((self.toad, toad_commit), (self.core, core_commit)):
            wheel = export.only_wheel(self.scratch / 'wheels' / f'{export.label}-{commit}')
            export.verify_wheel(wheel, installed)
        resources = Path(run(destination / 'bin/python', '-c',
                             'from agent_comms.native_package import MANIFEST; print(MANIFEST.parent)'))
        manifest = subprocess.check_output([
            'git', '-C', str(self.core.repository), 'show', f'{core_commit}:stack/pi-native.sha256'])
        if (resources / 'pi-native.sha256').read_bytes() != manifest:
            raise RuntimeError('Installed Core native pin differs from the clean export')
        run(destination / 'bin/python', '-I', '-B', '-c',
            'from agent_comms.native_package import pinned_native_package, verify_native_package; '
            'verify_native_package(pinned_native_package())')
        native_pin = hashlib.sha256(manifest).hexdigest()
        startup = check_startup(destination, self.scratch / f'startup-{destination.name}', self.baseline, self.thread)
        wake = check_message_wake(destination, self.scratch / f'wake-{destination.name}',
                                  self.scratch / f'startup-{destination.name}')
        record = {
            'baseline': str(self.baseline),
            'toad_commit': toad_commit, 'core_commit': core_commit,
            'native_manifest_sha256': native_pin,
            'packages': installed, 'runtime': str(destination),
            'startup': startup,
            'message_wake': wake,
        }
        (destination / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
        return destination

    def accept(self, runtime: Path, display: XvfbDisplay) -> None:
        """Exercise the installed schema after building or a required store conversion."""
        self.start_acceptance_thread(runtime)
        screenshot = open_saved_thread(
            runtime, self.thread, display, self.scratch / f'acceptance-{runtime.name}')
        (runtime / 'acceptance.json').write_text(json.dumps({'screenshot': str(screenshot)}) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toad-repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--core-repo', type=Path, required=True)
    parser.add_argument('--toad-ref', default='origin/main')
    parser.add_argument('--core-ref', default='origin/main')
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--thread', required=True, help='Existing saved thread; no new input')
    parser.add_argument('--start-thread', action='store_true',
                        help='Start the stopped acceptance thread from the built runtime')
    parser.add_argument('--start-env', type=Path,
                        help='Whitespace-separated NAME=VALUE entries for --start-thread')
    parser.add_argument('--display', help='Isolated Xvfb display for plain st acceptance')
    parser.add_argument('--qualify-runtime', type=Path, help='Finish gates on an existing unqualified candidate; build nothing')
    parser.add_argument('--build-only', action='store_true',
                        help='Build without attachment; incompatible stores must be converted before live acceptance')
    parser.add_argument('--scratch', type=Path, default=Path(__file__).resolve().parents[1] / '.artifacts/runtime-build')
    parser.add_argument('--runtimes', type=Path, default=Path.home() / '.local/share/agent-comms/runtimes')
    args = parser.parse_args()
    if args.start_thread != (args.start_env is not None):
        parser.error('--start-thread and --start-env must be used together')
    if args.build_only and args.start_thread:
        parser.error('--build-only cannot start an acceptance thread')
    if not args.build_only and args.display is None:
        parser.error('--display is required for an app check')
    build = RuntimeBuild(
        GitExport(args.toad_repo.resolve(), args.toad_ref, 'toad', 'batrachian-toad'),
        GitExport(args.core_repo.resolve(), args.core_ref, 'core', 'agent-comms'),
        args.baseline.resolve(strict=True),
        args.scratch.resolve(), args.runtimes.resolve(), args.thread,
        args.start_env.resolve(strict=True) if args.start_env else None,
    )
    runtime = build.qualify(args.qualify_runtime.resolve(strict=True)) if args.qualify_runtime else build.build()
    if not args.build_only:
        with XvfbDisplay(args.display) as display:
            build.accept(runtime, display)
    print(runtime)


if __name__ == '__main__':
    if '--prune-runtimes' in sys.argv or '--publish-runtime' in sys.argv:
        installation_main()
    elif sys.argv[1:] == ['--inventory']:
        print(json.dumps(inventory()))
    else:
        main()
