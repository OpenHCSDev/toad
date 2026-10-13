#!/usr/bin/env python3
"""Build an immutable Toad/Core checkpoint; publication stays with the coach.

Uses clean git exports and wheels, preserving the baseline's dependency set.
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
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import url2pathname
import zipfile

from performance.capture_live import XvfbDisplay


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


def observe_saved_thread(pid: int, thread: str, output: str) -> None:
    """Ask the running App's source now, then await its original publications."""
    import asyncio
    from agent_comms.mro_dispatch import MroDispatch, handles
    from performance.frame_meter import _running_app, targets
    from toad.core.events import AgentFail, SessionSelected
    from toad.core.source_events import TranscriptCoverage
    from toad.screens.main import MainScreen

    app = _running_app(pid)

    class Observation(MroDispatch):
        async def wait(self) -> None:
            self.completed = asyncio.get_running_loop().create_future()
            with ExitStack() as self.custody:
                self.custody.enter_context(app.events.subscribe(self.event))
                self.selected()
                await self.completed

        def event(self, event, subscription) -> None:
            self.dispatch_sync(event)

        @handles(SessionSelected)
        def selected(self, event=None) -> None:
            source = app.selected_session
            if not isinstance(source, MainScreen) or source._session_thread != thread:
                return
            transcript = source.presentation.transcript
            self.custody.enter_context(transcript.events.subscribe(self.event))
            agent = source.presentation.operational_agent
            if agent is not None:
                self.custody.enter_context(agent.events.subscribe(self.event))
            self.covered()

        @handles(TranscriptCoverage)
        def covered(self, event=None) -> None:
            source = app.selected_session
            if (not self.completed.done() and isinstance(source, MainScreen)
                    and source._session_thread == thread
                    and source.presentation.transcript.reports_coverage):
                targets(expected_pid=pid, output=output)
                self.completed.set_result(None)

        @handles(AgentFail)
        def failed(self, event) -> None:
            if self.completed.done():
                return
            Path(output).write_text(json.dumps({'error': f'{event.message}: {event.details}'}))
            self.completed.set_result(None)

    # The App owns this operation and its callback context, independent of paint.
    app.call_later(lambda: app.run_worker(Observation().wait(), group='saved-thread-observation'))


def open_saved_thread(runtime: Path, thread: str, display: XvfbDisplay, output: Path) -> Path:
    """Open only our own st on an explicitly isolated display, without input."""
    import os
    import psutil
    import time

    output.mkdir()
    env = dict(os.environ, DISPLAY=display.name, AGENT_COMMS_RUNTIME_ROOT=str(runtime / 'bin'), AGENT_COMMS_AGENT_BIN='pi')
    for name in ('NO_COLOR', 'TOAD_VALIDATION'):
        env.pop(name, None)
    with (output / 'st.log').open('w') as log:
        terminal = subprocess.Popen(['st', '-g', '150x48', '-e', 'toad-comms', thread], env=env, stdout=log, stderr=log)
        try:
            window = subprocess.check_output(['xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(terminal.pid)], env=env, text=True, timeout=30).strip()
            launch_title = subprocess.check_output(['xdotool', 'getwindowname', window], env=env, text=True)
            deadline = time.monotonic() + 30
            process = psutil.Process(terminal.pid)
            while not (children := [child for child in process.children() if child.name() == 'toad']):
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f'SavedThreadOpenFailed: {thread}; see {output / "st.log"}')
                time.sleep(0.1)
            # The app titles its terminal once its driver runs. A script sent to
            # the interpreter before that is lost while the process still starts.
            while subprocess.check_output(['xdotool', 'getwindowname', window], env=env, text=True) == launch_title:
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f'SavedThreadOpenFailed: {thread} never started its terminal; see {output / "st.log"}')
                time.sleep(0.1)
            targets = output / 'targets.json'
            remote = output / 'capture.py'
            remote.write_text(f'import sys\nsys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\nfrom build_runtime import observe_saved_thread\nobserve_saved_thread({children[0].pid}, {thread!r}, {str(targets)!r})\n')
            sys.remote_exec(children[0].pid, str(remote))
            while not targets.exists():
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    subprocess.run(['import', '-window', window, str(output / 'failed-thread.png')], env=env, check=False)
                    raise RuntimeError(f'SavedThreadAcceptanceFailed: no completed session observation for {thread}; see {output}')
                time.sleep(0.1)
            observation = json.loads(targets.read_text())
            if 'error' in observation:
                subprocess.run(['import', '-window', window, str(output / 'failed-thread.png')], env=env, check=False)
                raise RuntimeError(f'SavedThreadAcceptanceFailed: {thread}: {observation["error"]}; see {output}')
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
    package_name: str

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

    def verify_wheel(self, wheel: Path, installed: dict) -> None:
        # Hatch owns static/dynamic versions; this export owns its package identity.
        with zipfile.ZipFile(wheel) as archive:
            metadata_path, = (name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
            metadata = message_from_bytes(archive.read(metadata_path))
        name = metadata['Name'].lower().replace('_', '-')
        if name != self.package_name or installed[name]['version'] != metadata['Version']:
            raise RuntimeError(f'{self.package_name} differs from its clean-export wheel')

    @staticmethod
    def only_wheel(directory: Path) -> Path:
        wheel, = directory.glob('*.whl')
        return wheel


@dataclass(frozen=True)
class DependencySet:
    packages: dict
    replacements: tuple[GitExport, ...]

    @property
    def replaced_names(self) -> frozenset[str]:
        return frozenset(export.package_name for export in self.replacements)

    def requirements(self) -> list[str]:
        requirements = []
        replaced = self.replaced_names
        for name, package in sorted(self.packages.items()):
            if name in replaced:
                continue
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
        for name in self.replaced_names:
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
    display: XvfbDisplay

    def build(self) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.runtimes.mkdir(parents=True, exist_ok=True)
        dependencies = DependencySet(read_inventory(self.baseline / 'bin/python'), (self.toad, self.core))
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
            requirements.write_text('\n'.join(dependencies.requirements()) + '\n')
            # Atomic acquisition: an existing/borrowed prefix never enters cleanup.
            destination.mkdir()
            cleanup.callback(shutil.rmtree, destination)
            run('uv', 'venv', '--allow-existing', '--python', (self.baseline / 'bin/python').resolve(), destination)
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
            for export, wheel in ((self.toad, toad_wheel), (self.core, core_wheel)):
                export.verify_wheel(wheel, installed)
            record = {
                'baseline': str(self.baseline),
                'toad_commit': toad_commit, 'core_commit': core_commit,
                'native_manifest_sha256': native_pin, 'active_route': route,
                'packages': installed, 'runtime': str(destination),
            }
            record['screenshot'] = str(open_saved_thread(destination, self.thread, self.display, self.scratch / f'acceptance-{destination.name}'))
            (destination / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
            cleanup.pop_all()  # The completed immutable runtime leaves build custody.
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
    with XvfbDisplay(args.display) as display:
        build = RuntimeBuild(
            GitExport(args.toad_repo.resolve(), args.toad_ref, 'toad', 'batrachian-toad'),
            GitExport(args.core_repo.resolve(), args.core_ref, 'core', 'agent-comms'),
            args.baseline.resolve(strict=True),
            args.scratch.resolve(), args.runtimes.resolve(), args.thread, display,
        )
        print(build.build())


if __name__ == '__main__':
    if sys.argv[1:] == ['--inventory']:
        print(json.dumps(inventory()))
    elif sys.argv[1:] == ['--verify-route']:
        print(json.dumps(verify_route()))
    else:
        main()
