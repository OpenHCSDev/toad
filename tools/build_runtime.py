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
import importlib.util
import json
import os
import select
import signal
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile
from rich.cells import cell_len

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
    """Explicit removals or older build records allow pruning; process use vetoes it."""
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
                and (remove is not None or RuntimeBuild.qualified_before(path, built_at))]
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


def publication_module(publication_tools: Path):
    """Load the reviewed tools without changing the interpreter's Core package."""
    package_spec = importlib.util.spec_from_file_location(
        '_core_checkout_tools', publication_tools / '__init__.py')
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_spec.name] = package
    package_spec.loader.exec_module(package)
    spec = importlib.util.spec_from_file_location(
        '_core_checkout_tools.publish_runtime', publication_tools / 'publish_runtime.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def publish_runtime(publication_tools: Path, root: Path) -> None:
    """Select target files, then let the installed source own drain and stop."""
    from agent_comms.owner_cutover import StoppedOwnerInstallation
    from agent_comms.field_codec import FieldCodec

    module = publication_module(publication_tools)
    publication = module.RuntimePublication.installed()
    RuntimeBuild.recorded_baseline(publication.runtime)
    previous = StoppedOwnerInstallation.current_pointer().resolve(strict=True)
    subprocess.run([
        previous / 'bin/python', '-I', '-B', Path(__file__).resolve(), '--publish-source',
        '--publication-tools', publication_tools, '--root', root,
    ], input=json.dumps(FieldCodec.encode(publication)), text=True, check=True)
    print(f'Linked {publication.runtime}', flush=True)
    print(f'Previous {previous}', flush=True)


def publish_source(publication_tools: Path, root: Path) -> None:
    """Frontend readers and native owners stop under their original installed Core."""
    from agent_comms.field_codec import FieldCodec

    module = publication_module(publication_tools)
    publication = FieldCodec.decode(module.RuntimePublication, FieldCodec.parse(sys.stdin.read()))
    watchers = InstallWatchers(root / 'runtime-publication-readers.json')
    publication.publish(root, checkout=publication_tools.parent,
                        resources=watchers.publication(publication.runtime))


def installation_main() -> None:
    parser = argparse.ArgumentParser(description='Publish or prune qualified runtimes')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--prune-runtimes', action='store_true')
    actions.add_argument('--publish-runtime', action='store_true')
    actions.add_argument('--publish-source', action='store_true')
    actions.add_argument('--stop-watchers', action='store_true')
    actions.add_argument('--restore-watchers', action='store_true')
    parser.add_argument('--watcher-state', type=Path)
    parser.add_argument('--current', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--delete', action='store_true')
    parser.add_argument('--remove', type=Path, nargs='+',
                        help='Explicitly retire these runtimes, including unfinished builds')
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
        operation = publish_source if args.publish_source else publish_runtime
        operation(args.publication_tools, args.root)


@dataclass(frozen=True)
class InstallWatchers:
    """The install restores exactly the services it recorded before stopping."""

    path: Path

    def stop(self) -> None:
        units = json.loads(run('systemctl', '--user', 'list-units', '--type=service',
                               '--state=active', '--output=json'))
        names = [unit['unit'] for unit in units if unit['unit'] in (
            'codex-comms-inbox.service', 'opencode-comms-inbox.service', 'toad-serve.service',
            'agent-comms-connector.service')]
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

    @contextmanager
    def publication(self, runtime: Path):
        """Own frontend readers only; Core calls this AFTER its idle proof.

        Discover the bridge and desktop here, not before the drain: a bridge
        wrapper can be replaced while a worker finishes its turn.
        """
        import psutil
        from agent_comms.child_process import ObservedProcess, ProcessIdentity
        from agent_comms.maintenance_barrier import MaintenanceBarrier
        from agent_comms.owner_cutover import StoppedOwnerInstallation
        from agent_comms.store_files import _atomic_write_text
        from agent_comms.field_codec import FieldCodec

        bridge_path = self.path.with_suffix('.bridges.json')
        settings_backup = self.path.with_suffix('.settings.json')
        desktop_path = self.path.with_suffix('.desktop.json')
        settings_path = Path.home() / '.pi/agent/settings.json'
        previous = StoppedOwnerInstallation.current_pointer().resolve(strict=True)
        settings_before = settings_path.read_bytes()
        settings = json.loads(settings_before)
        compiled = compiled_global_extensions(runtime)
        old_compiled = compiled_global_extensions(previous)
        replacements = {str(old_compiled[key]): str(value) for key, value in compiled.items()}
        settings['extensions'] = [replacements.get(path, path) for path in settings['extensions']]

        def resume_bridges():
            if bridge_path.exists():
                for identity in FieldCodec.decode(tuple[ProcessIdentity, ...],
                        FieldCodec.parse(bridge_path.read_bytes())):
                    if identity.alive():
                        identity.signal(signal.SIGCONT)
                bridge_path.unlink()

        def restore_settings():
            if settings_backup.exists():
                if StoppedOwnerInstallation.current_pointer().resolve(strict=True) != runtime:
                    _atomic_write_text(settings_path, settings_backup.read_text(), fsync_parent=True)
                settings_backup.unlink()

        def restore_desktop():
            if not desktop_path.exists():
                return
            for saved in json.loads(desktop_path.read_text()):
                environment = {key: value for key, value in saved['environment'].items()
                    if not key.startswith(('AGENT_COMMS_', 'PI_', 'PYTHON'))
                    and key not in ('VIRTUAL_ENV', 'TMUX')}
                subprocess.Popen(saved['command'], env=environment, cwd=saved['cwd'],
                    start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            desktop_path.unlink()

        with ExitStack() as restore:
            # Register before each mutation, including partial context entry.
            restore.callback(restore_desktop)
            restore.callback(restore_settings)
            restore.callback(resume_bridges)
            resume_bridges()
            paused = []
            if self.path.exists():
                self.restore()
                self.path.unlink()
            restore.callback(lambda: (self.restore(), self.path.unlink()) if self.path.exists() else None)
            self.stop()
            desktop = json.loads(desktop_path.read_text()) if desktop_path.exists() else []
            for process in psutil.process_iter():
                try:
                    identity = ProcessIdentity.capture(process.pid)
                except ProcessLookupError:
                    continue
                try:
                    command = process.cmdline()
                    if not command:
                        continue
                    bridges = []
                    for child in process.children():
                        try:
                            child_identity = ProcessIdentity.capture(child.pid)
                        except ProcessLookupError:
                            continue
                        if any(Path(arg).name == 'agent-comms-claude-bridge' for arg in child.cmdline()):
                            bridges.append(child_identity)
                    if bridges and any('agent-comms-claude-bridge watch' in arg for arg in command):
                        paused.append(identity)
                        _atomic_write_text(bridge_path, json.dumps(FieldCodec.encode(tuple(paused))),
                                           fsync_parent=True)
                        identity.signal(signal.SIGSTOP)
                        for bridge_identity in bridges:
                            ObservedProcess(bridge_identity).stop_sync()
                    elif Path(command[0]).name == 'toad':
                        terminal = process.parent()
                        if terminal.name() != 'st' or terminal.environ().get('DISPLAY') != ':0':
                            continue
                        desktop.append({'command': ['st', '-e', str(Path.home() / 'bin/toad-comms')],
                                        'cwd': terminal.cwd(), 'environment': terminal.environ()})
                        _atomic_write_text(desktop_path, json.dumps(desktop), fsync_parent=True)
                        ObservedProcess(identity).stop_sync()
                except psutil.NoSuchProcess:
                    continue
            if not settings_backup.exists():
                _atomic_write_text(settings_backup, settings_before.decode('utf-8'), fsync_parent=True)
            _atomic_write_text(settings_path, json.dumps(settings, indent=2) + '\n', fsync_parent=True)
            try:
                yield
            finally:
                restoration = restore.pop_all()
                if not MaintenanceBarrier(self.path.parent / 'registry.json').read().turn_pending:
                    restoration.close()


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
    """Own one isolated st window, its screen and physical X input."""

    columns, rows = 140, 40

    def __init__(self, command, display, output, environment, cwd):
        self.command, self.display, self.output = command, display, output
        self.environment = dict(environment, DISPLAY=display.name)
        self.cwd = cwd

    def __enter__(self):
        import psutil
        self.output.mkdir(parents=True, exist_ok=True)
        self.dump = self.output / 'st-screen.txt'
        self.log = (self.output / 'st.log').open('w')
        self.terminal = subprocess.Popen(
            ['st', '-f', 'DejaVu Sans Mono:pixelsize=16', '-g', f'{self.columns}x{self.rows}',
             '-o', str(self.dump), '-e', 'env', f'HOME={self.environment["HOME"]}',
             *map(str, self.command)],
            cwd=self.cwd, env=self.environment, stdout=self.log, stderr=self.log)
        self.owner = psutil.Process(self.terminal.pid)
        self.created = self.owner.create_time()
        try:
            self.window = int(subprocess.check_output(
                ['xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(self.terminal.pid)],
                env=self.environment, text=True, timeout=10).splitlines()[0])
            # -o enables st's raw printer too; Ctrl+Print leaves only explicit dumps.
            self.keys('ctrl+Print')
            self.wait('terminal', lambda text: bool(text.strip()))
            (self.output / 'process-tree.txt').write_text(subprocess.check_output(
                ['ps', '--forest', '-o', 'pid,ppid,args', '-p', str(self.owner.pid),
                 '--ppid', str(self.owner.pid)], text=True))
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def capture(self):
        """Read st's own print-screen output; screenshots record the visible window."""
        offset = self.dump.stat().st_size
        self.keys('shift+Print')
        deadline = time.monotonic() + 2
        while True:
            with self.dump.open('rb') as stream:
                stream.seek(offset)
                data = stream.read()
            if data.count(b'\n') >= self.rows - 1:
                return data.decode('utf-8')
            if self.terminal.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('st did not finish its screen dump')
            time.sleep(.02)

    @staticmethod
    def message_cells(text):
        """Decode the middle pane through the terminal's sidebar boundaries."""
        for line in text.splitlines():
            panes = line.split('│')
            if len(panes) >= 2:
                yield '│'.join(panes[1:-1] if len(panes) >= 3 else panes[1:])

    @staticmethod
    def message_rows(text):
        """Visible transcript rows between the sidebar separators.

        The conversation's CursorContainer paints the leading gutter on every
        message row. Splitting the outer separators preserves Unicode message
        text and any table separators inside it, without copying sidebar state.
        """
        rows = []
        for body in TerminalApp.message_cells(text):
            if body.startswith('▌'):
                # The jump control overlays messages; it is not their text.
                control = '↓ Back to bottom · Esc'
                rows.append(body.replace(control, ' ' * len(control)))
        return tuple(rows)

    @staticmethod
    def reader_position(text):
        """First visible message and its screen row, excluding the scrollbar gutter."""
        for row, line in enumerate(text.splitlines()):
            panes = line.split('│')
            if len(panes) >= 3:
                body = '│'.join(panes[1:-1])[:-2]
                if body.startswith('▌') and body.strip('▌ '):
                    return row, body
        return ()

    def reader_place(self, name):
        """Observe a settled message viewport after one navigation action."""
        previous = ()

        def settled(text):
            nonlocal previous
            rows = self.reader_position(text)
            # This connection banner occupies a transcript row until it closes.
            # Compare reader positions only after the viewport has its full height.
            same = ('Agent Comms connected' not in text
                    and bool(rows) and rows == previous)
            previous = rows
            return same

        return self.reader_position(self.wait(name, settled))

    def screenshot(self, name):
        path = self.output / f'{name}.png'
        run('import', '-display', self.display.name, '-window', str(self.window), path)
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
        XvfbDisplay.input(self.owner, self.created, self.window, 'key', '--clearmodifiers', *keys)

    def show_saved_thread(self, thread):
        self.wait('saved-ready', lambda text: thread in text
                  and '▶ Session details · Ready' in '\n'.join(text.splitlines()[-8:]))
        # The thread sidebar starts collapsed; expand its visible right gutter.
        self.click_cell(self.columns - 1, self.rows // 2)
        return self.wait('saved', lambda text: 'User messages' in text and all(
            'Indexing' not in line.split('│', 1)[0] for line in text.splitlines()))

    def click(self, label):
        text = self.wait('find-' + label.replace('/', '-'), lambda text: any(
            label in line.split('│', 1)[0] for line in text.splitlines()))
        row, line = next((row, line) for row, line in enumerate(text.splitlines())
                         if label in line.split('│', 1)[0])
        self.click_cell(cell_len(line[:line.index(label)]) + cell_len(label) // 2, row)

    def hide_category(self, label):
        """Click this checkbox in the right sidebar, never matching saved message text."""
        def control(text):
            return next(((row, line) for row, line in enumerate(text.splitlines())
                         if '│' in line and label in line.rsplit('│', 1)[-1]), None)
        text = self.wait('find-filter-' + label.replace('/', '-'), lambda text: control(text) is not None)
        row, line = control(text)
        prefix, panel = line.rsplit('│', 1)
        self.click_cell(cell_len(prefix + '│' + panel[:panel.index('▐')]) + 1, row)

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
                self.keys('ctrl+q')
                try:
                    self.terminal.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.terminal.terminate()
                    self.terminal.wait(timeout=5)
        finally:
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


@dataclass(frozen=True)
class CopiedCheck:
    """The one open Core context used by both visible checks."""

    worker: subprocess.Popen[str]
    environment: dict[str, str]
    thread: str
    home: Path
    result: dict


@contextmanager
def check_startup(runtime: Path, output: Path, baseline: Path, thread: str) -> Iterator[CopiedCheck]:
    """Keep Core's bounded check root open through startup and the fresh reply."""
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
    saved = json.loads(run(baseline / 'bin/python', '-I', '-B', '-c', '''
import json,sys,os
from agent_comms.active_route import read_active_route
from agent_comms.comms import wire
from agent_comms.launch_runtime import RestartEnvironment
c=wire(read_active_route());t=c.registry.require(sys.argv[1])
print(json.dumps(dict(root=str(c.root),path=str(t.runtime.path),model=t.model,
    config=str(RestartEnvironment.inherit(os.environ).native_config))))
''', thread))
    home = output / 'home'
    home.mkdir(mode=0o700)
    agent = output / 'pi'
    agent.mkdir(mode=0o700)
    config = Path(saved['config'])
    settings = json.loads((config / 'settings.json').read_text())
    compiled = compiled_global_extensions(runtime)
    settings['extensions'] = [str(path) for path in compiled.values()]
    (agent / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    (agent / 'extensions').mkdir()
    for extension in (config / 'extensions').iterdir():
        if extension not in compiled:
            (agent / 'extensions' / extension.name).symlink_to(extension)
    saved['agent_directory'] = str(agent)
    (output / 'saved-source.json').write_text(json.dumps(saved, indent=2))
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('AGENT_COMMS_', 'PI_', 'XDG_'))
                   and k not in ('PYTHONPATH', 'PYTHONHOME', 'NO_COLOR', 'TOAD_VALIDATION')}
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                       XDG_STATE_HOME=str(home / 'state'), XDG_DATA_HOME=str(home / 'data'),
                       AGENT_COMMS_RUNTIME_ROOT=str(runtime / 'bin'),
                       AGENT_COMMS_NATIVE_CONFIG_DIR=str(config), PI_CODING_AGENT_DIR=str(agent))
    with (output / 'check-root.log').open('w') as log:
        worker = subprocess.Popen([str(python), '-I', '-B', '-c', '''
import json,sys,time,os
from pathlib import Path
from agent_comms.active_route import ActiveRoute,publish_active_route
from agent_comms.check_root import CheckRoot
from agent_comms.comms import Comms
out,runtime,source=map(Path,sys.argv[1:4]);name=sys.argv[4]
with CheckRoot(Comms(source),(name,),out/'wire').open() as c:
    os.environ['HOME']=str(out/'home')
    publish_active_route(ActiveRoute(c.root,c.bus.log.private_marker_unlocked().root_id))
    thread=c.registry.require(name)
    sender=c.messaging.user_identity(thread.worktree).name
    c.owners.start(name,agent_bin=str(runtime/'bin/pi-comms-native'),agent_args=())
    print('READY',flush=True)
    request=sys.stdin.readline()
    if request:
        request=json.loads(request)
        result=Path(request['output']);token=request['token']
        (result/'input.json').write_text(json.dumps(dict(status='UNKNOWN',replay=False,target=name)))
        started=time.monotonic()
        c.messaging.send_user_message(name,'Reply with '+token+'. Do not use tools.',worktree=thread.worktree)
        while True:
            failures=list((c.root/'diagnostics').glob('drain-*.json'))
            if failures:raise RuntimeError(f'Private check produced drain diagnostics: {failures}')
            with c.bus.log.opened_wire_snapshot() as history:
                replies=[m for m in history.newest_messages(1024*1024)
                         if m.sender==name and m.target==sender and token in m.body]
            if replies and not c.registry.require(name).executing:break
            time.sleep(.25)
        (result/'result.json').write_text(json.dumps(dict(completed=True,reply=replies[0].body,
            session=thread.session_file,root=str(c.root),thread=name,drain_diagnostics=0,
            reply_seconds=time.monotonic()-started)))
        (result/'input.json').write_text(json.dumps(dict(status='COMPLETED',replay=False,target=name)))
        sys.stdin.read()
''', str(output), str(runtime), saved['root'], thread],
            env={**environment, 'HOME': os.environ['HOME']},
            stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=log, text=True)
        try:
            readable, _, _ = select.select([worker.stdout], [], [], 60)
            if not readable or worker.stdout.readline().strip() != 'READY':
                raise RuntimeError(f'Private check did not start; see {output / "check-root.log"}')
            with BuildDisplay(output) as display:
                command = [runtime / 'bin/toad']
                with TerminalApp(command, display, output / 'plain', environment, home) as app:
                    app.wait('store', lambda text: 'Toad' in text or 'agent' in text.lower())
                    app.screenshot('store')
                command = ['/home/ts/bin/toad-comms', thread]
                with TerminalApp(command, display, output / 'welcome', environment, home) as app:
                    app.wait('welcome', lambda text: thread in text)
                    app.screenshot('welcome')
                    app.click(thread)
                    app.show_saved_thread(thread)
                    app.screenshot('saved')
                    initial = app.reader_place('plain-initial')
                    app.click_cell(app.columns // 2, app.rows - 4)
                    app.keys('Page_Up', 'Page_Up', 'Page_Up')
                    app.wait('plain-page-up-moved', lambda text: bool(app.reader_position(text))
                             and app.reader_position(text) != initial)
                    plain_before = app.reader_place('plain-before')
                    app.click('#any')
                    app.wait('any', lambda text: '#any · all comms' in text and 'IRC / Markdown' in text)
                    app.screenshot('any')
                    app.click('#comms')
                    app.wait('comms', lambda text: '#comms' in '\n'.join(text.splitlines()[:3])
                             and 'IRC / Markdown' in text)
                    app.screenshot('comms')
                    app.click(thread)
                    app.wait('plain-return', lambda text: app.reader_position(text) == plain_before)
                    check_filtered_return(app, thread)
            result = dict(import_count=len(modules), plain='passed', welcome='passed', saved='passed',
                          channel='passed', comms='passed', filtered_return='passed', evidence=str(output))
            (output / 'result.json').write_text(json.dumps(result, indent=2))
            yield CopiedCheck(worker, environment, thread, home, result)
        finally:
            worker.stdin.close()
            worker.wait(timeout=150)
            worker.stdout.close()
            if worker.returncode:
                raise RuntimeError(f'Private check failed; see {output / "check-root.log"}')


def check_filtered_return(app: TerminalApp, thread: str) -> None:
    """Choose user-only checkboxes, PageUp and compare the visible returned rows."""
    app.wait('saved-return', lambda text: 'User messages' in text)
    for label in ('Agent messages', 'Messages in', 'Messages out', 'Thinking', 'Tool calls', 'Other / notices'):
        app.hide_category(label)
    app.click_cell(app.columns // 2, app.rows - 4)
    initial = app.reader_place('filtered-initial')
    app.screenshot('filtered-initial')
    app.keys('Page_Up', 'Page_Up', 'Page_Up')
    app.wait('page-up-moved', lambda text: bool(app.reader_position(text))
             and app.reader_position(text) != initial)
    expected = app.reader_place('filtered-before')
    app.screenshot('filtered-before')
    app.click('#any')
    app.wait('filtered-away', lambda text: '#any · all comms' in text and 'IRC / Markdown' in text)
    app.keys('Escape')
    app.wait('filtered-return', lambda text: app.reader_position(text) == expected)
    app.screenshot('filtered-return')
    app.click('#any')
    app.wait('filtered-click-away', lambda text: '#any · all comms' in text and 'IRC / Markdown' in text)
    app.click(thread)
    app.wait('filtered-click-return', lambda text: app.reader_position(text) == expected)
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






def check_message_wake(output: Path, copied: CopiedCheck) -> dict:
    """Send one fresh DM in the same Core check root and observe its tab return."""
    output.mkdir(mode=0o700)
    token = 'BUILD_WAKE_' + str(time.time_ns())
    with BuildDisplay(output) as display:
        command = ['/home/ts/bin/toad-comms', copied.thread]
        with TerminalApp(command, display, output / 'reply', copied.environment, copied.home) as app:
            app.wait('welcome', lambda text: copied.thread in text)
            app.click(copied.thread)
            app.show_saved_thread(copied.thread)
            app.screenshot('before-send')
            copied.worker.stdin.write(json.dumps(dict(output=str(output), token=token)) + '\n')
            copied.worker.stdin.flush()

            def reply_is_visible(text):
                return any(row.strip('▌ ') == token for row in app.message_cells(text))

            def replied(text):
                if copied.worker.poll() is not None:
                    raise RuntimeError('Private check exited before the reply was observed')
                return (output / 'result.json').exists() and reply_is_visible(text)

            app.wait('reply', replied, seconds=None)
            app.screenshot('reply')
            app.click('#any')
            app.wait('reply-channel', lambda text: '#any · all comms' in text
                     and 'IRC / Markdown' in text and reply_is_visible(text))
            app.click(copied.thread)
            app.wait('reply-return', lambda text: reply_is_visible(text) and 'User messages' in text)
            app.screenshot('reply-return')
    return json.loads((output / 'result.json').read_text())


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

    def qualify(self, destination: Path, *, message_check=check_message_wake) -> Path:
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
                           self.baseline, self.thread) as copied:
            wake = message_check(self.scratch / f'wake-{destination.name}', copied)
            startup = copied.result
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
        '--prune-runtimes', '--publish-runtime', '--publish-source', '--stop-watchers', '--restore-watchers')):
        installation_main()
    elif sys.argv[1:] == ['--inventory']:
        print(json.dumps(inventory()))
    else:
        main()
