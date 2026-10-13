#!/usr/bin/env python3
"""Build an immutable Toad/Core checkpoint; publication stays with the coach.

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
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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


def install_saved_thread_observer(pid: int, thread: str, output: str) -> None:
    """Install before App startup, or ask an already-running App immediately."""
    from functools import partial
    from textual._context import NoActiveAppError
    from performance.frame_meter import _running_app
    from toad.application_lifetime import ApplicationLifetime

    def start(app) -> None:
        app.run_worker(
            SavedThreadObservation(app, pid, thread, output).wait(),
            group='saved-thread-observation',
        )

    try:
        app = _running_app(pid)
    except NoActiveAppError:
        ApplicationLifetime.observe_next_start(lambda lifetime: start(lifetime.app))
    else:
        app.schedule_from_thread(partial(start, app))


class SavedThreadObservation:
    """One accepted session's source readiness and failure publications."""

    def __init__(self, app, pid: int, thread: str, output: str) -> None:
        self.app, self.pid, self.thread, self.output = app, pid, thread, output

    async def wait(self) -> None:
        import asyncio
        import traceback
        from agent_comms.mro_dispatch import MroDispatch, handles
        from performance.frame_meter import targets
        from toad.core.events import AgentFail, SessionAgentAttached, SessionSelected
        from toad.core.source_events import TranscriptCoverage
        from toad.screens.main import MainScreen

        observation = self

        class Events(MroDispatch):
            def __init__(self) -> None:
                self.transcript = self.agent = None

            def event(self, event, subscription) -> None:
                self.dispatch_sync(event)

            @handles(SessionSelected, SessionAgentAttached)
            def selected(self, event=None) -> None:
                source = observation.app.selected_session
                if (not isinstance(source, MainScreen)
                        or source.agent_session_id != observation.thread):
                    return
                transcript = source.presentation.transcript
                if self.transcript is not transcript:
                    self.transcript = transcript
                    observation.subscriptions.enter_context(transcript.events.subscribe(self.event))
                    conversation = source.presentation.widget
                    if conversation is not None:
                        observation.subscriptions.enter_context(
                            conversation.core_publications.subscribe(self.event))
                agent = source.attached_agent
                if agent is not None and self.agent is not agent:
                    self.agent = agent
                    observation.subscriptions.enter_context(agent.events.subscribe(self.event))
                    if failure := agent.session.disposition.current_failure():
                        self.failed(failure)
                self.covered()

            @handles(TranscriptCoverage)
            def covered(self, event=None) -> None:
                source = observation.app.selected_session
                if (not observation.completed.done() and isinstance(source, MainScreen)
                        and source.agent_session_id == observation.thread
                        and source.presentation.transcript.reports_coverage):
                    targets(expected_pid=observation.pid, output=observation.output)
                    observation.completed.set_result(None)

            @handles(AgentFail)
            def failed(self, event) -> None:
                if observation.completed.done():
                    return
                Path(observation.output).write_text(json.dumps(
                    {'error': f'{event.message}: {event.details}'}))
                observation.completed.set_result(None)

        self.completed = asyncio.get_running_loop().create_future()
        try:
            with ExitStack() as self.subscriptions:
                events = Events()
                self.subscriptions.enter_context(self.app.events.subscribe(events.event))
                events.selected()
                await self.completed
        except BaseException:
            Path(self.output).write_text(json.dumps({'error': traceback.format_exc()}))
            raise


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
            deadline = time.monotonic() + 30
            process = psutil.Process(terminal.pid)
            while not (children := [child for child in process.children()
                                    if child.name() == 'toad']):
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f'SavedThreadOpenFailed: {thread}; see {output / "st.log"}')
                time.sleep(0.1)
            targets = output / 'targets.json'
            attempt = 0
            while True:
                attempt += 1
                remote = output / f'capture-{attempt}.py'
                status = output / f'capture-{attempt}.status'
                remote.write_text(f'''import sys
_ready = (hasattr(sys.modules.get("pathlib"), "PurePosixPath")
          and hasattr(sys.modules.get("textual.app"), "App")
          and hasattr(sys.modules.get("toad.application_lifetime"), "ApplicationLifetime"))
if not _ready:
    open({str(status)!r}, "w").write("not-ready")
else:
    import json, traceback
    try:
        sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
        from build_runtime import install_saved_thread_observer
        install_saved_thread_observer({children[0].pid}, {thread!r}, {str(targets)!r})
    except BaseException:
        open({str(targets)!r}, "w").write(json.dumps({{"error": traceback.format_exc()}}))
    open({str(status)!r}, "w").write("installed")
''')
                try:
                    sys.remote_exec(children[0].pid, str(remote))
                except RuntimeError as error:
                    if str(error) not in (
                        "Can't find the main thread in the remote process",
                        "Can't find a running interpreter in the remote process",
                    ):
                        raise
                else:
                    while not status.exists():
                        if terminal.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError(f'SavedThreadOpenFailed: observer injection did not settle for {thread}; see {output}')
                        time.sleep(0.1)
                    if status.read_text() == 'installed':
                        break
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f'SavedThreadOpenFailed: no ready Python main thread for {thread}; see {output}')
                time.sleep(0.1)
            remaining = max(0.1, deadline - time.monotonic())
            window = subprocess.check_output(['xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(terminal.pid)], env=env, text=True, timeout=remaining).strip()
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
    display: XvfbDisplay

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
            run('uv', 'pip', 'check', '--python', python)
            installed = read_inventory(python)
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
