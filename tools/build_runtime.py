#!/usr/bin/env python3
"""Build, qualify and publish a reviewed Toad/Core runtime.

Uses clean git exports and wheels, with dependencies owned by Toad's locked graph.
Native package verification belongs to Core's native_package module.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
import hashlib
import importlib.metadata
import json
import os
import select
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile

# Isolated Python omits the script directory; this tool owns its sibling imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def prune_runtimes(current: Path, previous: Path, *, delete: bool, remove: list[Path] | None = None) -> dict:
    """Records and build dates admit removal; process references can only veto it."""
    selected = current.resolve(strict=True)
    previous = previous.resolve(strict=True)
    directory = selected.parent
    if previous.parent != directory or not current.is_symlink():
        raise ValueError('Current and previous must be installed sibling runtimes')
    runtimes = sorted(directory.iterdir())
    if any(path.is_symlink() or not path.is_dir() for path in runtimes):
        raise ValueError('Runtime directory contains unexpected files or symlinks')
    if remove is not None:
        if any(path not in runtimes for path in remove):
            raise ValueError('Removal must name installed sibling runtimes')
        runtimes = remove
    baseline = RuntimeBuild.recorded_baseline(selected)
    installed = {selected, previous, baseline}
    built_at = RuntimeBuild.built_at(selected)
    references = runtime_references(runtimes)
    proposed = [path for path in runtimes
                if path not in installed and not references[str(path)]
                and RuntimeBuild.qualified_before(path, built_at)]
    result = {'before': len(runtimes), 'current': str(selected), 'previous': str(previous),
              'baseline': str(baseline),
              'kept': [str(path) for path in runtimes if path not in proposed],
              'kept_by_pid': {path: pids for path, pids in references.items() if pids},
              'would_delete': list(map(str, proposed)), 'deleted': []}
    free_before = shutil.disk_usage(directory).free
    if delete:
        for path in proposed:
            if current.resolve(strict=True) != selected:
                raise RuntimeError('Default changed during runtime cleanup')
            borrowers = runtime_references([path])[str(path)]
            if borrowers:
                result['kept_by_pid'][str(path)] = borrowers
                result['kept'].append(str(path))
                continue
            shutil.rmtree(path)
            result['deleted'].append(str(path))
            print(f'Removed unused runtime {path}', file=sys.stderr, flush=True)
    result['after'] = len(list(directory.iterdir()))
    result['filesystem_free_change_bytes'] = shutil.disk_usage(directory).free - free_before
    return result


def publish_runtime(publication_tools: Path, root: Path) -> None:
    """Use Core's publication owner and report the runtime it replaced.

    Run with the qualified target Python inside the reviewed publication window.
    Native stopping/restarting remains with Core's existing cutover owner.
    """
    publisher = (publication_tools / 'publish_runtime.py').resolve(strict=True)
    sys.path.insert(0, str(publisher.parents[1]))
    from tools.publish_runtime import RuntimePublication
    from agent_comms.owner_cutover import StoppedOwnerInstallation

    publication = RuntimePublication.installed()
    RuntimeBuild.recorded_baseline(publication.runtime)
    previous = StoppedOwnerInstallation.current_pointer().resolve(strict=True)
    if previous == publication.runtime:
        raise ValueError('Runtime is already current; do not repeat publication')
    publication.publish(root)
    print(f'Linked {publication.runtime}', flush=True)
    # Report the actual prior pointer, not a build baseline or a persistent list.
    print(f'Previous {previous}', flush=True)


def installation_main() -> None:
    parser = argparse.ArgumentParser(description='Publish or prune qualified runtimes')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--prune-runtimes', action='store_true')
    actions.add_argument('--publish-runtime', action='store_true')
    actions.add_argument('--stop-watchers', action='store_true')
    actions.add_argument('--restore-watchers', action='store_true')
    parser.add_argument('--watcher-state', type=Path)
    parser.add_argument('--current', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--delete', action='store_true')
    parser.add_argument('--remove', type=Path, nargs='+', help='Prune only these runtime directories')
    parser.add_argument('--publication-tools', type=Path, help="Core checkout's tools directory")
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if args.stop_watchers or args.restore_watchers:
        if args.watcher_state is None:
            parser.error('watcher stop/restore requires --watcher-state')
        watchers = InstallWatchers(args.watcher_state)
        watchers.stop() if args.stop_watchers else watchers.restore()
    elif args.prune_runtimes:
        if args.current is None or args.previous is None:
            parser.error('--prune-runtimes requires --current and --previous')
        print(json.dumps(prune_runtimes(args.current, args.previous, delete=args.delete, remove=args.remove), indent=2))
    else:
        if args.publication_tools is None or args.root is None:
            parser.error('--publish-runtime requires --publication-tools and --root')
        publish_runtime(args.publication_tools, args.root)


@dataclass(frozen=True)
class InstallWatchers:
    """The install restores exactly the services it recorded before stopping."""

    path: Path

    def stop(self) -> None:
        units = json.loads(run('systemctl', '--user', 'list-units', '--type=service',
                               '--state=active', '--output=json'))
        names = [unit['unit'] for unit in units if unit['unit'] in (
            'codex-comms-inbox.service', 'opencode-comms-inbox.service', 'toad-serve.service')]
        with self.path.open('x') as output:
            json.dump(names, output)
            output.flush()
            os.fsync(output.fileno())
        if names:
            run('systemctl', '--user', 'stop', *names)

    def restore(self) -> None:
        names = json.loads(self.path.read_text())
        if names:
            run('systemctl', '--user', 'start', *names)
            for name in names:
                run('systemctl', '--user', 'is-active', name)
        print(json.dumps({'watchers_restarted': names}))


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
            ['st', '-g', f'{self.columns}x{self.rows}', '-e',
             'env', f'HOME={self.environment["HOME"]}', 'tmux', '-S', str(self.socket),
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
            geometry = self.mux('display-message', '-p', '-t', 'qualify:0.0',
                                '#{pane_width} #{pane_height}')
            geometry.check_returncode()
            self.columns, self.rows = map(int, geometry.stdout.split())
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def capture(self):
        result = self.mux('capture-pane', '-p', '-t', 'qualify:0.0')
        return result.stdout if result.returncode == 0 else ''

    @staticmethod
    def message_cells(text):
        """Decode the middle pane through the terminal's sidebar boundaries."""
        for line in text.splitlines():
            panes = line.split('│')
            if len(panes) >= 2:
                yield '│'.join(panes[1:-1] if len(panes) >= 3 else panes[1:])

    @staticmethod
    def message_rows(text):
        """Visible transcript rows between the sidebar separators, without its scrollbar.

        The conversation's CursorContainer paints the leading gutter on every
        message row. Splitting the outer separators preserves Unicode message
        text and any table separators inside it, without copying sidebar state.
        """
        rows = []
        for body in TerminalApp.message_cells(text):
            if body.startswith('▌'):
                # The jump control overlays messages; it is not their text.
                control = '↓ Back to bottom · Esc'
                rows.append(body[:-2].replace(control, ' ' * len(control)))
        return tuple(rows)

    def reader_place(self, name):
        """Observe a settled message viewport after one navigation action."""
        previous = ()

        def settled(text):
            nonlocal previous
            rows = self.message_rows(text)
            same = bool(rows) and rows == previous
            previous = rows
            return same

        return self.message_rows(self.wait(name, settled))

    def screenshot(self, name):
        path = self.output / f'{name}.png'
        run('import', '-display', self.display.name, '-window', 'root', path)
        return path

    def wait(self, name, predicate, seconds=40):
        deadline = None if seconds is None else time.monotonic() + seconds
        previous = ''
        changes = self.output / f'{name}-changes.txt'
        while True:
            text = self.capture()
            if text != previous:
                with changes.open('a') as log:
                    log.write(f'\n--- {time.monotonic()} ---\n{text}')
                previous = text
            if predicate(text):
                (self.output / f'{name}.txt').write_text(text)
                return text
            if self.terminal.poll() is not None or (deadline is not None and time.monotonic() >= deadline):
                (self.output / f'{name}-failed.txt').write_text(text)
                self.screenshot(f'{name}-failed')
                raise RuntimeError(f'Terminal probe {name} failed; see {self.output}')
            time.sleep(.2)

    def keys(self, *keys):
        self.mux('send-keys', '-t', 'qualify:0.0', *keys).check_returncode()

    def show_saved_thread(self, thread):
        self.wait('saved-ready', lambda text: thread in text
                  and '▶ Session details · Ready' in '\n'.join(text.splitlines()[-8:]))
        # The thread sidebar starts collapsed; expand its visible right gutter.
        self.click_cell(self.columns - 1, self.rows // 2)
        return self.wait('saved', lambda text: 'User messages' in text and all(
            'Indexing' not in line.split('│', 1)[0] for line in text.splitlines()))

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


def compiled_global_extensions(runtime: Path) -> dict[Path, Path]:
    """Read our global extension paths from the selected package's declaration."""
    package = Path(run(runtime / 'bin/python', '-I', '-B', '-c',
                       'from agent_comms.native_package import pinned_native_package; '
                       'print(pinned_native_package())'))
    manifest = json.loads((package / 'dist/agent-comms-imports.json').read_text())
    return {Path(row['sources'][0]['path']).parent: package / row['entry']
            for row in manifest['extensionEntries'] if row.get('sources')
            and Path(row['sources'][0]['path']).parent.name in
            ('agent-comms', 'project-sync', 'web-search')}


@contextmanager
def check_startup(runtime: Path, output: Path, baseline: Path, thread: str) -> Iterator[dict]:
    """Own the copied history through startup and its caller's private fork/wake."""
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
                     config=str(RestartEnvironment.inherit(os.environ).native_config))))
''', thread))
    project = output / 'project'
    project.mkdir(mode=0o700)
    agent = output / 'pi'
    agent.mkdir(mode=0o700)
    config = Path(saved['config'])
    settings = json.loads((config / 'settings.json').read_text())
    compiled = compiled_global_extensions(runtime)
    settings['extensions'] = [str(path) for path in compiled.values()]
    (agent / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    # Keep third-party discovery unchanged; our three globals use compiled files.
    (agent / 'extensions').mkdir()
    for extension in (config / 'extensions').iterdir():
        if extension not in compiled:
            (agent / 'extensions' / extension.name).symlink_to(extension)
    saved['agent_directory'] = str(agent)
    with Path(saved['path']).open('rb') as stream:
        captured = stream.read(os.fstat(stream.fileno()).st_size)
    captured = captured[:captured.rfind(b'\n') + 1]
    if not captured:
        raise ValueError('Startup requires nonempty saved history')
    source = project / 'saved.jsonl'
    with ExitStack() as startup:
        with source.open('wb') as stream:
            startup.callback(source.unlink)
            stream.write(captured)
        source.chmod(0o600)
        (output / 'saved-source.json').write_text(json.dumps(saved, indent=2))
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith(('AGENT_COMMS_', 'PI_', 'XDG_'))
                       and k not in ('PYTHONPATH', 'PYTHONHOME', 'NO_COLOR', 'TOAD_VALIDATION')}
        environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                           XDG_STATE_HOME=str(home / 'state'), XDG_DATA_HOME=str(home / 'data'),
                           AGENT_COMMS_ROOT=str(output / 'wire'),
                           AGENT_COMMS_RUNTIME_ROOT=str(runtime / 'bin'))
        launch = subprocess.check_output([str(python), '-I', '-B', '-c', '''
import sys,json
from pathlib import Path
from agent_comms.comms import wire
from agent_comms.active_route import ActiveRoute,publish_active_route
from agent_comms.coordinator import Coordination
from agent_comms.agent_backend import AgentBackend
from agent_comms.field_codec import FieldCodec
from agent_comms.launch_runtime import RestartEnvironment
c=wire();root_id=c.messaging.initialize_private_initial_protocol()
publish_active_route(ActiveRoute(c.root,root_id))
c.registry.declare(c.registry.new_thread('startup-saved',frozenset(),sys.argv[1],session_file=sys.argv[2],
    backend=FieldCodec.decode(type[AgentBackend],sys.argv[3]),model=json.loads(sys.argv[5])))
with Coordination(str(c.root/'coordination.sqlite3')) as store:store.install_private_runtime()
print(json.dumps(RestartEnvironment(root=str(c.root),
    native_config=Path(sys.argv[4]),agent_directory=Path(sys.argv[6])).encode()))
''', str(project), str(source), saved['backend'], saved['config'], json.dumps(saved['model']), str(agent)],
            env=environment, text=True)
        environment.update(json.loads(launch))
        startup.callback(subprocess.run, [runtime / 'bin/agent-comms', '--root', output / 'wire',
                         'stop', '--name', 'startup-saved'], env=environment, check=True)
        subprocess.run([runtime / 'bin/agent-comms', '--root', output / 'wire',
                        'start', '--name', 'startup-saved'], env=environment, check=True)
        with BuildDisplay(output) as display:
            command = [runtime / 'bin/toad']
            with TerminalApp(command, display, output / 'plain', environment, home) as app:
                app.wait('store', lambda text: 'Toad' in text or 'agent' in text.lower())
                app.screenshot('store')
            command = ['/home/ts/bin/toad-comms', 'startup-saved']
            with TerminalApp(command, display, output / 'welcome', environment, home) as app:
                app.wait('welcome', lambda text: 'startup-saved' in text)
                app.screenshot('welcome')
                app.click('startup-saved')
                app.show_saved_thread('startup-saved')
                app.screenshot('saved')
                initial = app.reader_place('plain-initial')
                app.click_cell(app.columns // 2, app.rows // 2)
                app.keys('PPage', 'PPage', 'PPage')
                app.wait('plain-page-up-moved', lambda text: bool(app.message_rows(text))
                         and app.message_rows(text) != initial)
                plain_before = app.reader_place('plain-before')
                app.click('#any')
                app.wait('any', lambda text: '#any · all comms' in text and 'IRC / Markdown' in text)
                app.screenshot('any')
                app.keys('Escape')
                app.wait('plain-return', lambda text: app.message_rows(text) == plain_before)
                check_filtered_return(app)
        result = dict(import_count=len(modules), plain='passed', welcome='passed', saved='passed',
                      channel='passed', filtered_return='passed', evidence=str(output))
        (output / 'result.json').write_text(json.dumps(result, indent=2))
        yield result


def check_filtered_return(app: TerminalApp) -> None:
    """Choose user-only checkboxes, PageUp and compare the visible returned rows."""
    app.wait('saved-return', lambda text: 'User messages' in text)
    for label in ('Agent messages', 'Messages in', 'Messages out', 'Thinking', 'Tool calls', 'Other / notices'):
        app.click(label)
    app.click_cell(app.columns // 2, app.rows - 5)
    initial = app.reader_place('filtered-initial')
    app.keys('PPage', 'PPage', 'PPage')
    app.wait('page-up-moved', lambda text: bool(app.message_rows(text))
             and app.message_rows(text) != initial)
    expected = app.reader_place('filtered-before')
    app.screenshot('filtered-before')
    app.click('#any')
    app.wait('filtered-away', lambda text: '#any · all comms' in text and 'IRC / Markdown' in text)
    app.keys('Escape')
    app.wait('filtered-return', lambda text: app.message_rows(text) == expected)
    app.screenshot('filtered-return')
    app.click('#any')
    app.wait('filtered-click-away', lambda text: '#any · all comms' in text and 'IRC / Markdown' in text)
    app.click('startup-saved')
    app.wait('filtered-click-return', lambda text: app.message_rows(text) == expected)
    app.screenshot('filtered-click-return')


def open_saved_thread(runtime: Path, thread: str, display: XvfbDisplay, output: Path) -> Path:
    """Open our own terminal and observe the requested thread without app internals."""
    environment = dict(os.environ, AGENT_COMMS_RUNTIME_ROOT=str(runtime / 'bin'),
                       AGENT_COMMS_AGENT_BIN='pi')
    for name in ('NO_COLOR', 'TOAD_VALIDATION'):
        environment.pop(name, None)
    with TerminalApp(['toad-comms', thread], display, output / 'saved', environment, Path.home()) as app:
        app.show_saved_thread(thread)
        return app.screenshot('saved-thread')






def check_message_wake(runtime: Path, output: Path, startup: Path) -> dict:
    """Deliver one new message to a fresh private SDK fork and require its reply."""
    output.mkdir(mode=0o700)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('AGENT_COMMS_', 'PI_', 'XDG_'))
                   and k not in ('PYTHONPATH', 'PYTHONHOME')}
    environment['BUILD_WAKE_TOKEN'] = 'BUILD_WAKE_' + str(time.time_ns())
    with (output / 'wake.log').open('w') as log:
        worker = subprocess.Popen([str(runtime / 'bin/python'), '-I', '-B', '-c', '''
import asyncio,hashlib,json,os,sys,time
from pathlib import Path
from agent_comms.active_route import ActiveRoute,publish_active_route
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
os.environ.update(HOME=str(home), PI_CODING_AGENT_DIR=str(out/'pi'),
                  AGENT_COMMS_NATIVE_CONFIG_DIR=saved['config'])
for kind in ('CONFIG','DATA','STATE','CACHE'):os.environ['XDG_'+kind+'_HOME']=str(out/kind.lower())
c=Comms(out/'wire');root_id=c.messaging.initialize_private_initial_protocol()
route=ActiveRoute(c.root,root_id)
publish_active_route(route)
os.environ.update(AGENT_COMMS_ROOT=str(c.root),AGENT_COMMS_AGENT_BIN=str(runtime/'bin/pi-comms-native'))
c=wire(route)
parent=c.registry.declare(c.registry.new_thread('build-parent',frozenset(),str(out),session_file=str(source),
    backend=FieldCodec.decode(type[AgentBackend],saved['backend']),model=saved['model']),StoppedThreadStatus())
async def fork():return await parent.backend.fork(parent,str(runtime/'bin/pi-comms-native'),LaunchRuntime.running())
forked=asyncio.run(fork())
child=c.registry.declare(c.registry.new_thread('build-wake',frozenset(),str(out),parent=parent.name,
    session_file=forked.path,backend=parent.backend,model=parent.model),StoppedThreadStatus())
c.registry.declare(c.registry.new_thread('build-sender',frozenset(),str(out)),StoppedThreadStatus())
os.environ['PI_CODING_AGENT_DIR']=saved['agent_directory']
c.owners.start(child.name,agent_bin=str(runtime/'bin/pi-comms-native'),agent_args=())
try:
    print('READY',flush=True)
    if sys.stdin.readline().strip() != 'SEND':raise RuntimeError('UI did not request the fresh message')
    token=os.environ['BUILD_WAKE_TOKEN']
    (out/'input.json').write_text(json.dumps(dict(status='UNKNOWN',replay=False,target=child.name)))
    started=time.monotonic()
    sent=c.messaging.send('build-sender',child.name,'Reply with '+token+'. Do not use tools.')
    for notice in sent.notices:print(notice,file=sys.stderr,flush=True)
    while True:
        failures=list((c.root/'diagnostics').glob('drain-*.json'))
        if failures:raise RuntimeError(f'Private wake produced a drain diagnostic: {failures}')
        messages=[m for line in c.bus.log.path.read_text().splitlines()
                  for m in WireRecord.public_from_wire(json.loads(line)).messages()]
        replies=[m for m in messages if m.sender==child.name and m.target=='build-sender' and token in m.body]
        current=c.registry.require(child.name)
        if replies and not current.turn_state.active.executing:break
        time.sleep(.25)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    (out/'result.json').write_text(json.dumps(dict(completed=True,reply=replies[-1].body,
        session=forked.path,original_unchanged=True,drain_diagnostics=0,reply_seconds=time.monotonic()-started)))
    (out/'input.json').write_text(json.dumps(dict(status='COMPLETED',replay=False,target=child.name)))
finally:
    if not c.registry.require(child.name).turn_state.active.executing:
        c.owners.stop(child.name)
''', str(output), str(startup), str(runtime)], env=environment, stdout=subprocess.PIPE,
            stdin=subprocess.PIPE, stderr=log, text=True)
        try:
            readable, _, _ = select.select([worker.stdout], [], [], 60)
            if not readable or worker.stdout.readline().strip() != 'READY':
                raise RuntimeError(f'Private agent did not start; see {output / "wake.log"}')
            environment.update(HOME=str(output / 'home'), AGENT_COMMS_ROOT=str(output / 'wire'),
                               AGENT_COMMS_RUNTIME_ROOT=str(runtime / 'bin'))
            saved = json.loads((startup / 'saved-source.json').read_text())
            environment['AGENT_COMMS_NATIVE_CONFIG_DIR'] = saved['config']
            environment['PI_CODING_AGENT_DIR'] = saved['agent_directory']
            for kind in ('CONFIG', 'DATA', 'STATE', 'CACHE'):
                environment['XDG_' + kind + '_HOME'] = str(output / kind.lower())
            with BuildDisplay(output) as display:
                command = ['/home/ts/bin/toad-comms', 'build-wake']
                with TerminalApp(command, display, output / 'reply', environment, output) as app:
                    app.wait('welcome', lambda text: 'build-wake' in text)
                    app.click('build-wake')
                    app.show_saved_thread('build-wake')
                    app.screenshot('before-send')
                    worker.stdin.write('SEND\n')
                    worker.stdin.flush()
                    token = environment['BUILD_WAKE_TOKEN']
                    def replied(text):
                        if worker.poll() not in (None, 0):
                            raise RuntimeError(f'Private agent failed; see {output / "wake.log"}')
                        return (output / 'result.json').exists() and token in text
                    app.wait('reply', replied, seconds=None)
                    app.screenshot('reply')
                    app.click('#any')
                    app.wait('reply-channel', lambda text: '#any · all comms' in text
                             and 'IRC / Markdown' in text and token in text)
                    app.click('build-wake')
                    app.wait('reply-return', lambda text: token in text and 'User messages' in text)
                    app.screenshot('reply-return')
            worker.wait(timeout=30)
            if worker.returncode:
                raise RuntimeError(f'Private agent failed; see {output / "wake.log"}')
            return json.loads((output / 'result.json').read_text())
        finally:
            worker.stdin.close()
            if worker.poll() is None:
                worker.wait(timeout=150)
            worker.stdout.close()











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
    record = Path('build.json')
    timestamp_format = '%Y%m%dT%H%M%SZ'

    @classmethod
    def built_at(cls, runtime: Path) -> datetime:
        return datetime.strptime(runtime.name.rsplit('-', 1)[-1], cls.timestamp_format)

    @classmethod
    def recorded_baseline(cls, runtime: Path) -> Path:
        record = json.loads((runtime / cls.record).read_text())
        declared = Path(record['runtime'])
        baseline = Path(record['baseline'])
        if declared != runtime or not baseline.is_absolute():
            raise ValueError(f'Build record does not describe {runtime}')
        return baseline

    @classmethod
    def qualified_before(cls, runtime: Path, cutoff: datetime) -> bool:
        if not (runtime / cls.record).is_file():
            return False
        cls.recorded_baseline(runtime)
        return cls.built_at(runtime) < cutoff

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
        stamp = datetime.now(timezone.utc).strftime(self.timestamp_format)
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
                'from agent_comms.private_path import PrivateDirectoryRole; '
                'verify_native_package(Path(sys.argv[1])); '
                'Path(sys.argv[2]).mkdir(mode=PrivateDirectoryRole.permissions)',
                native_source, resources / native_relative.parents[2])
            if any(path.stat().st_mode & 0o222 for path in native_source.rglob('*') if path.is_file()):
                raise ValueError('Shared native package files must be immutable')
            shutil.copytree(native_source, resources / native_relative, copy_function=os.link)
            run(destination / 'bin/toad', '--version')
            run(python, '-c', 'import toad.cli, agent_comms.cli, textual, formbridge, objectstate')
            # Keep an installed but unqualified candidate available for diagnosis.
            # Only the qualification record certifies readiness; never rebuild to inspect it.
            cleanup.pop_all()
        return destination

    def qualify(self, destination: Path) -> Path:
        """Finish the existing readiness checks on an installed candidate."""
        if (destination / self.record).exists():
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
        with check_startup(destination, self.scratch / f'startup-{destination.name}',
                           self.baseline, self.thread) as startup:
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
        (destination / self.record).write_text(json.dumps(record, indent=2) + '\n')
        print('qualify: ok', flush=True)
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
    parser.add_argument('--package-only', action='store_true',
                        help='Build for a separate private UI check; send no input and write no build.json')
    parser.add_argument('--build-only', action='store_true',
                        help='Build without attachment; incompatible stores must be converted before live acceptance')
    parser.add_argument('--scratch', type=Path, default=Path(__file__).resolve().parents[1] / '.artifacts/runtime-build')
    parser.add_argument('--runtimes', type=Path, default=Path.home() / '.local/share/agent-comms/runtimes')
    args = parser.parse_args()
    if args.start_thread != (args.start_env is not None):
        parser.error('--start-thread and --start-env must be used together')
    if args.build_only and args.start_thread:
        parser.error('--build-only cannot start an acceptance thread')
    if args.package_only and (not args.build_only or args.qualify_runtime):
        parser.error('--package-only requires --build-only and cannot qualify a runtime')
    if not args.build_only and args.display is None:
        parser.error('--display is required for an app check')
    build = RuntimeBuild(
        GitExport(args.toad_repo.resolve(), args.toad_ref, 'toad', 'batrachian-toad'),
        GitExport(args.core_repo.resolve(), args.core_ref, 'core', 'agent-comms'),
        args.baseline.resolve(strict=True),
        args.scratch.resolve(), args.runtimes.resolve(), args.thread,
        args.start_env.resolve(strict=True) if args.start_env else None,
    )
    runtime = args.qualify_runtime.resolve(strict=True) if args.qualify_runtime else build.build()
    if not args.package_only:
        runtime = build.qualify(runtime)
    if not args.build_only:
        with XvfbDisplay(args.display) as display:
            build.accept(runtime, display)
    print(runtime)


if __name__ == '__main__':
    if any(option in sys.argv for option in (
        '--prune-runtimes', '--publish-runtime', '--stop-watchers', '--restore-watchers')):
        installation_main()
    elif sys.argv[1:] == ['--inventory']:
        print(json.dumps(inventory()))
    else:
        main()
