#!/usr/bin/env python3
"""Build an immutable Toad/Core checkpoint; publication stays with the coach.

Uses clean git exports and wheels, preserving the baseline's dependency set.
Native package verification belongs to Core's native_package module.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import url2pathname
import zipfile


def run(*args: str | Path, cwd: Path | None = None) -> str:
    print("+ " + " ".join(map(str, args)), file=sys.stderr, flush=True)
    return subprocess.check_output(list(map(str, args)), cwd=cwd, text=True).strip()


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


def verify_route() -> dict:
    """Core owns route decoding, root identity and the selected native tree."""
    from agent_comms.active_route import read_active_route
    from agent_comms.field_codec import FieldCodec
    from agent_comms.native_package import MANIFEST, NativePackageError, verify_native_package

    route = read_active_route()
    if route is None:
        raise RuntimeError('No active route is installed')
    route.observe_root()
    try:
        verify_native_package(route.native_package)
    except NativePackageError as error:
        pin = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        raise RuntimeError(
            f'NativeRoutePinVerificationFailed: Core pin {pin}; '
            f'route native_package {route.native_package}: {error}. '
            'Run stack/bin/prepare-pi-native from the clean Core export, '
            'then have the coach replace the route native_package. No old-package fallback.'
        ) from error
    return FieldCodec.encode(route)


def observe_saved_thread(pid: int, output: str) -> None:
    """Enter the real App's next dispatch, not remote_exec's empty context."""
    from performance.frame_meter import targets
    from textual.app import App

    dispatch = App._dispatch_message

    async def observe(app, message):
        App._dispatch_message = dispatch  # One observation on our own fresh App.
        await dispatch(app, message)

        def capture_ready() -> None:
            presentation = app.selected_session.presentation
            agent = presentation.operational_agent
            if agent is None or not agent.ready or presentation.transcript.displayed_cursor is None:
                app.set_timer(0.1, capture_ready)
                return
            targets(expected_pid=pid, output=output)

        app.call_after_refresh(capture_ready)

    App._dispatch_message = observe


def open_saved_thread(runtime: Path, thread: str, display: str, output: Path) -> Path:
    """Open only our own st on an explicitly isolated display, without input."""
    import os
    import psutil
    import time

    if display.split('.')[0] == ':0':
        raise ValueError('Use an isolated Xvfb display, not the desktop')
    output.mkdir()
    env = dict(os.environ, DISPLAY=display, AGENT_COMMS_RUNTIME_ROOT=str(runtime / 'bin'), AGENT_COMMS_AGENT_BIN='pi')
    for name in ('NO_COLOR', 'TOAD_VALIDATION'):
        env.pop(name, None)
    with (output / 'st.log').open('w') as log:
        terminal = subprocess.Popen(['st', '-g', '150x48', '-e', 'toad-comms', thread], env=env, stdout=log, stderr=log)
        try:
            window = subprocess.check_output(['xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(terminal.pid)], env=env, text=True, timeout=30).strip()
            deadline = time.monotonic() + 30
            process = psutil.Process(terminal.pid)
            while not (children := [child for child in process.children() if child.name() == 'toad']):
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f'SavedThreadOpenFailed: {thread}; see {output / "st.log"}')
                time.sleep(0.1)
            time.sleep(1)  # Allow the actual application's event loop to start.
            targets = output / 'targets.json'
            remote = output / 'capture.py'
            remote.write_text(f'import sys\nsys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\nfrom build_runtime import observe_saved_thread\nobserve_saved_thread({children[0].pid}, {str(targets)!r})\n')
            sys.remote_exec(children[0].pid, str(remote))
            while not targets.exists():
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    subprocess.run(['import', '-window', window, str(output / 'failed-thread.png')], env=env, check=False)
                    raise RuntimeError(f'SavedThreadAcceptanceFailed: no completed session observation for {thread}; see {output}')
                time.sleep(0.1)
            screenshot = output / 'saved-thread.png'
            subprocess.run(['import', '-window', window, str(screenshot)], env=env, check=True)
            return screenshot
        finally:
            if terminal.poll() is None:
                terminal.terminate()  # Only this build's st, never a backend owner.
                terminal.wait(timeout=5)


@dataclass(frozen=True)
class GitExport:
    repository: Path
    revision: str
    label: str

    @property
    def commit(self) -> str:
        return run('git', '-C', self.repository, 'rev-parse', self.revision + '^{commit}')

    def wheel(self, commit: str, exports: Path, cache: Path) -> Path:
        wheels = cache / f'{self.label}-{commit}'
        if wheels.exists():
            return self.only_wheel(wheels)
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
        run('uv', 'build', '--wheel', '--out-dir', wheels, source)
        return self.only_wheel(wheels)

    @staticmethod
    def only_wheel(directory: Path) -> Path:
        wheel, = directory.glob('*.whl')
        return wheel


@dataclass(frozen=True)
class DependencySet:
    packages: dict

    def requirements(self) -> list[str]:
        requirements = []
        for name, package in sorted(self.packages.items()):
            if name in ('agent-comms', 'batrachian-toad'):
                continue  # These are the two clean exports being replaced.
            source = package['source']
            if source is None:
                requirements.append(f"{name}=={package['version']}")
            elif 'vcs_info' in source:
                # uv owns its cache and reuse; pass the recorded full commit.
                commit = source['vcs_info']['commit_id']
                url = source['url']
                subdirectory = source.get('subdirectory')
                fragment = f'#subdirectory={subdirectory}' if subdirectory else ''
                requirements.append(f"{name} @ git+{url}@{commit}{fragment}")
            else:
                # Our preceding build records reviewed wheels as file URLs.
                # Preserve that exact source, never rebuild a local checkout.
                if 'dir_info' in source or 'archive_info' not in source:
                    raise RuntimeError(f'{name} has a directory/editable source; supply a reviewed wheel baseline')
                url = urlsplit(source['url'])
                if url.scheme != 'file' or url.netloc not in ('', 'localhost'):
                    raise RuntimeError(f'{name} is not a local wheel source: {source["url"]}')
                wheel = Path(url2pathname(url.path))
                if url.query or wheel.suffix != '.whl' or not wheel.is_file():
                    raise RuntimeError(f'{name} wheel source is missing or is not a wheel: {source["url"]}')
                requirements.append(source['url'])
        return requirements

    def verify(self, installed: dict) -> None:
        expected = {name: p['version'] for name, p in self.packages.items()}
        observed = {name: p['version'] for name, p in installed.items()}
        for name in ('agent-comms', 'batrachian-toad'):
            expected[name] = observed[name]  # Their versions come from the exports.
        if expected != observed:
            raise RuntimeError(f'Dependency set changed: baseline={expected!r}, built={observed!r}')


@dataclass(frozen=True)
class RuntimeBuild:
    toad: GitExport
    core: GitExport
    baseline: Path
    scratch: Path
    runtimes: Path
    thread: str
    display: str

    def build(self) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.runtimes.mkdir(parents=True, exist_ok=True)
        dependencies = DependencySet(read_inventory(self.baseline / 'bin/python'))
        toad_commit, core_commit = self.toad.commit, self.core.commit
        manifest = subprocess.check_output([
            'git', '-C', str(self.core.repository), 'show', f'{core_commit}:stack/pi-native.sha256'
        ])
        native_pin = hashlib.sha256(manifest).hexdigest()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        destination = self.runtimes / f'toad-{toad_commit[:9]}-core-{core_commit[:9]}-native-{native_pin[:16]}-{stamp}'
        if destination.exists():
            raise FileExistsError(f'Refusing to change an existing runtime: {destination}')
        cache = self.scratch / 'wheels'
        with tempfile.TemporaryDirectory(prefix='export-', dir=self.scratch) as temporary:
            exports = Path(temporary)
            toad_wheel = self.toad.wheel(toad_commit, exports, cache)
            core_wheel = self.core.wheel(core_commit, exports, cache)
            requirements = exports / 'requirements.txt'
            requirements.write_text('\n'.join(dependencies.requirements()) + '\n')
            run('uv', 'venv', '--python', (self.baseline / 'bin/python').resolve(), destination)
            python = destination / 'bin/python'
            # Exact baseline dependencies are deliberate; pip check rejects skew.
            run('uv', 'pip', 'install', '--python', python, '--no-deps', '-r', requirements, toad_wheel, core_wheel)
            run('uv', 'pip', 'check', '--python', python)
            installed = read_inventory(python)
            dependencies.verify(installed)
            # Locate through Core, not an assumed interpreter/version layout.
            resources = Path(run(python, '-c', 'from agent_comms.native_package import MANIFEST; print(MANIFEST.parent)'))
            if (resources / 'pi-native.sha256').read_bytes() != manifest:
                raise RuntimeError('Installed Core native pin differs from the clean export')
            route = json.loads(run(python, Path(__file__).resolve(), '--verify-route'))
            run(destination / 'bin/toad', '--version')
            run(python, '-c', 'import toad.cli, agent_comms.cli, textual, formbridge, objectstate')
            # Hatch owns static and dynamic versions; consume its wheel metadata.
            for wheel in (toad_wheel, core_wheel):
                with zipfile.ZipFile(wheel) as archive:
                    metadata_path, = (name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
                    metadata = message_from_bytes(archive.read(metadata_path))
                name = metadata['Name'].lower().replace('_', '-')
                if installed[name]['version'] != metadata['Version']:
                    raise RuntimeError(f'{name} version differs from its clean-export wheel')
            record = {
                'baseline': str(self.baseline),
                'toad_commit': toad_commit, 'core_commit': core_commit,
                'native_manifest_sha256': native_pin, 'active_route': route,
                'packages': installed, 'runtime': str(destination),
            }
            record['screenshot'] = str(open_saved_thread(destination, self.thread, self.display, self.scratch / f'acceptance-{destination.name}'))
            (destination / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
        return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toad-repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--core-repo', type=Path, required=True)
    parser.add_argument('--toad-ref', default='origin/main')
    parser.add_argument('--core-ref', default='origin/main')
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--thread', required=True, help='Existing saved thread; no owner restart or new input')
    parser.add_argument('--display', required=True, help='Isolated Xvfb display for plain st acceptance')
    parser.add_argument('--scratch', type=Path, default=Path(__file__).resolve().parents[1] / '.artifacts/runtime-build')
    parser.add_argument('--runtimes', type=Path, default=Path.home() / '.local/share/agent-comms/runtimes')
    args = parser.parse_args()
    build = RuntimeBuild(
        GitExport(args.toad_repo.resolve(), args.toad_ref, 'toad'),
        GitExport(args.core_repo.resolve(), args.core_ref, 'core'),
        args.baseline.resolve(strict=True),
        args.scratch.resolve(), args.runtimes.resolve(), args.thread, args.display,
    )
    print(build.build())


if __name__ == '__main__':
    if sys.argv[1:] == ['--inventory']:
        print(json.dumps(inventory()))
    elif sys.argv[1:] == ['--verify-route']:
        print(json.dumps(verify_route()))
    else:
        main()
