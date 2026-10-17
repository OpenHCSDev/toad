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
    if os.geteuid() != 0:
        raise PermissionError('Runtime reference inspection requires sudo')
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
    sys.path.insert(0, str(publication_tools.resolve(strict=True)))
    from publish_runtime import RuntimePublication

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
    print(run('sudo', '-n', sys.executable, Path(__file__).resolve(), '--prune-runtimes',
              '--current', publication.current, '--previous', previous, '--delete'))


def installation_main() -> None:
    parser = argparse.ArgumentParser(description='Publish or prune qualified runtimes')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--prune-runtimes', action='store_true')
    actions.add_argument('--publish-runtime', action='store_true')
    parser.add_argument('--current', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--delete', action='store_true')
    parser.add_argument('--publication-tools', type=Path)
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


def check_startup(runtime: Path, output: Path, baseline: Path, thread: str) -> dict:
    """Import the installed family and paint welcome with copied saved history."""
    import psutil

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
    name='.'.join(('toad',*parts))
    importlib.import_module(name)
    names.append(name)
print(json.dumps(names))
'''))
    (output / 'imports.json').write_text(json.dumps(modules, indent=2))
    home = output / 'home'
    home.mkdir(mode=0o700)
    saved = json.loads(run(baseline / 'bin/python', '-I', '-B', '-c', '''
import json,sys
from agent_comms.active_route import read_active_route
from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
c=wire(read_active_route()); t=c.registry.require(sys.argv[1])
print(json.dumps(dict(path=str(t.runtime.path), backend=FieldCodec.encode(t.backend), model=t.model,
                     package=str(read_active_route().native_package))))
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
    private = dict(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                   XDG_STATE_HOME=str(home / 'state'), XDG_DATA_HOME=str(home / 'data'),
                   AGENT_COMMS_ROOT=str(output / 'wire'))
    environment.update(private)
    subprocess.run([str(python), '-I', '-B', '-c', '''
import sys
from agent_comms.comms import wire
from agent_comms.coordinator import Coordination
from agent_comms.threads import Thread
from agent_comms.agent_backend import AgentBackend
from agent_comms.field_codec import FieldCodec
c=wire(); c.messaging.initialize_private_initial_protocol()
c.registry.declare(Thread('startup-saved',frozenset(),sys.argv[1],session_file=sys.argv[2],
    backend=FieldCodec.decode(type[AgentBackend],sys.argv[3])))
with Coordination(str(c.root/'coordination.sqlite3')) as store: store.install_private_runtime()
''', str(project), str(source), saved['backend']],
                   env=environment, check=True)
    with (output / 'xvfb.log').open('w') as log:
        server = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0',
                                   '1440x960x24', '-nolisten', 'tcp'],
                                  stdout=subprocess.PIPE, stderr=log)
        try:
            display_name = ':' + server.stdout.readline().decode().strip()
            with XvfbDisplay(display_name) as display:
                environment['DISPLAY'] = display.name
                for name, arguments, selected in (
                    ('plain', [], 'store'),
                    ('welcome', ['acp', f'{python} -I -B -m agent_comms.acp', str(home)], 'welcome'),
                    ('saved', ['acp', f'{python} -I -B -m agent_comms.acp', str(home),
                               '--session', 'startup-saved'], 'saved'),
                ):
                    observation = output / f'{name}.json'
                    completed = output / 'any.json' if name == 'saved' else observation
                    exit_status = output / f'{name}-exit-code'
                    with (output / f'{name}.log').open('w') as terminal_log:
                        terminal = subprocess.Popen(
                            ['st', '-g', '140x34', '-e', 'env',
                             *(f'{k}={v}' for k, v in private.items()),
                             f'TOAD_STARTUP_EXIT={exit_status}', 'sh', '-c',
                             '"$@"; code=$?; printf "%s\\n" "$code" > "$TOAD_STARTUP_EXIT"; exit "$code"',
                             'toad-startup', str(runtime / 'bin/toad'), *arguments],
                            cwd=home, env=environment, stdout=terminal_log, stderr=terminal_log)
                        try:
                            deadline = time.monotonic() + 30
                            remote = output / f'{name}-observe.py'
                            remote.write_text(f'''import sys,json
from pathlib import Path
if 'toad.app' in sys.modules and hasattr(sys.modules['toad.app'], 'ToadApp'):
 from textual.app import App
 from textual._context import NoActiveAppError
 try: app=App.running_app()
 except NoActiveAppError: pass
 else:
  def observe():
   if app._exception is not None: raise app._exception
   if {selected!r} == 'store':
    if app.current_mode != 'store': return
   elif {selected!r} == 'saved':
    from toad.screens.main import MainScreen
    from toad.screens.comms import CommsScreen
    from toad.widgets.conversation import Conversation
    screen=app.selected_session
    if Path({str(observation)!r}).exists():
     if not isinstance(screen, CommsScreen) or screen.target != '#any': return
     from toad.widgets.comms_chat import CommsChatView
     chat=screen.query_one_optional(CommsChatView)
     if chat is None or not chat.prompt.is_on_screen: return
    else:
     if not isinstance(screen, MainScreen) or screen.agent_session_id != 'startup-saved': return
     conversation=screen.query_one(Conversation)
     if conversation.transcript.displayed_cursor is None: return
     if not screen.presentation.transcript.reports_coverage: return
   else:
    from toad.screens.welcome import WelcomeScreen, WelcomeThreads
    from toad.navigation_target import ThreadTarget
    if not isinstance(app.selected_session, WelcomeScreen): return
    rows=[row for group in app.selected_session.walk_children(WelcomeThreads)
          for row in group.member_container.children]
    rows=[row for row in rows if row.target == ThreadTarget('startup-saved')]
    if not rows: return
   text=[strip.text for strip in app.screen._compositor.render_strips()]
   if not any(line.strip() for line in text): return
   if {selected!r} == 'welcome' and not any('startup-saved' in line for line in text): return
   destination=Path({str(completed)!r}) if {name!r} == 'saved' and Path({str(observation)!r}).exists() else Path({str(observation)!r})
   destination.write_text(json.dumps(dict(mode=app.current_mode, text=text)))
  app.schedule_from_thread(observe)
''')
                            child = None
                            channel_opened = False
                            while not completed.exists():
                                crashes = list(home.rglob('Terminal_crash_*.txt'))
                                if crashes:
                                    raise RuntimeError(f'{name} crashed: {crashes}')
                                if terminal.poll() is not None or time.monotonic() >= deadline:
                                    run('import', '-display', display.name, '-window', 'root', output / f'{name}-failed.png')
                                    raise RuntimeError(f'{name} launch did not paint; see {output}')
                                if child is None:
                                    children = [process for process in psutil.Process(terminal.pid).children(recursive=True)
                                                if str(runtime / 'bin/toad') in process.cmdline()
                                                and process.name() != 'sh']
                                    if children:
                                        child, = children
                                if child is not None:
                                    if not child.is_running():
                                        raise RuntimeError(f'{name} child exited before painting; see {output}')
                                    subprocess.run(['sudo', '-n', str(python), '-I', '-B', '-c',
                                                    f'import sys; sys.remote_exec({child.pid}, {str(remote)!r})'],
                                                   check=True, timeout=5)
                                    if name == 'saved' and observation.exists() and not channel_opened:
                                        run('import', '-display', display.name, '-window', 'root', output / 'saved.png')
                                        navigation = output / 'open-any.py'
                                        navigation.write_text('''from textual.app import App
from toad.navigation_target import NavigationTarget
app=App.running_app()
def open_channel():
 app.run_worker(app.selected_session.open_sidebar_target(NavigationTarget.named('#any')))
app.schedule_from_thread(open_channel)
''')
                                        channel_opened = True
                                        subprocess.run(['sudo', '-n', str(python), '-I', '-B', '-c',
                                                        f'import sys; sys.remote_exec({child.pid}, {str(navigation)!r})'],
                                                       check=True, timeout=5)
                                time.sleep(.5)
                            run('import', '-display', display.name, '-window', 'root', output / f'{completed.stem}.png')
                            window = subprocess.check_output(
                                ['xdotool', 'search', '--onlyvisible', '--pid', str(terminal.pid)],
                                env=environment, text=True).strip()
                            XvfbDisplay.input(psutil.Process(terminal.pid),
                                              psutil.Process(terminal.pid).create_time(), int(window), 'key', 'ctrl+q')
                            terminal_code = terminal.wait(timeout=10)
                            (output / f'{name}-terminal-exit-code').write_text(str(terminal_code))
                            if int(exit_status.read_text()) != 0:
                                raise RuntimeError(f'{name} exited unsuccessfully; see {output}')
                            crashes = list(home.rglob('Terminal_crash_*.txt'))
                            if crashes:
                                raise RuntimeError(f'{name} crashed: {crashes}')
                        finally:
                            if terminal.poll() is None:
                                terminal.terminate()
                                terminal.wait(timeout=5)
        finally:
            server.terminate()
            server.wait(timeout=5)
    result = dict(import_count=len(modules), plain='passed', welcome='passed', saved='passed', channel='passed', evidence=str(output))
    (output / 'result.json').write_text(json.dumps(result, indent=2))
    return result


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
from agent_comms.threads import Thread
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
                  AGENT_COMMS_NATIVE_CONFIG_DIR='/home/ts/.pi/agent')
for kind in ('CONFIG','DATA','STATE','CACHE'):os.environ['XDG_'+kind+'_HOME']=str(out/kind.lower())
c=Comms(out/'wire');root_id=c.messaging.initialize_private_initial_protocol()
route=ActiveRoute(c.root,root_id,Path(saved['package']))
path=active_route_path();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
path.write_text(json.dumps(FieldCodec.encode(route)));path.chmod(0o600)
os.environ.update(AGENT_COMMS_ROOT=str(c.root),AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
    AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=saved['package'],AGENT_COMMS_AGENT_BIN=str(runtime/'bin/pi-comms-native'))
c=wire(route)
parent=c.registry.declare(Thread('build-parent',frozenset(),str(out),session_file=str(source),
    backend=FieldCodec.decode(type[AgentBackend],saved['backend']),model=saved['model']),StoppedThreadStatus())
async def fork():return await parent.backend.fork(parent,str(runtime/'bin/pi-comms-native'),LaunchRuntime.running())
forked=asyncio.run(fork())
child=c.registry.declare(Thread('build-wake',frozenset(),str(out),parent=parent.name,
    session_file=forked.path,backend=parent.backend,model=parent.model),StoppedThreadStatus())
c.registry.declare(Thread('build-sender',frozenset(),str(out)),StoppedThreadStatus())
os.environ['PI_CODING_AGENT_DIR']='/home/ts/.pi/agent'
c.owners.start(child.name,agent_bin=str(runtime/'bin/pi-comms-native'),agent_args=())
try:
    sent=c.messaging.send_message('build-sender',child.name,'Reply exactly BUILD_WAKE_OK. Do not use tools.')
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
    return json.loads((output / 'result.json').read_text())


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

    def failed(self, details: str) -> None:
        if self.completed.done():
            return
        Path(self.output).write_text(json.dumps({'error': details}))
        self.completed.set_result(None)

    async def wait(self) -> None:
        import traceback
        try:
            await self.observe()
        except BaseException:
            Path(self.output).write_text(json.dumps({'error': traceback.format_exc()}))
            raise

    async def observe(self) -> None:
        import asyncio
        import traceback
        from agent_comms.mro_dispatch import MroDispatch, handles
        from performance.frame_meter import targets
        from toad.core.events import AgentFail, SessionAgentAttached, SessionSelected
        from toad.core.source_events import TranscriptCoverage
        from toad.screens.main import MainScreen

        observation = self
        self.completed = asyncio.get_running_loop().create_future()

        class Events(MroDispatch):
            def __init__(self) -> None:
                self.transcript = self.agent = None

            def event(self, event, subscription) -> None:
                try:
                    self.dispatch_sync(event)
                except BaseException:
                    observation.failed(traceback.format_exc())

            @handles(SessionSelected, SessionAgentAttached)
            def selected(self, event=None) -> None:
                source = observation.app.selected_session
                if not isinstance(source, MainScreen):
                    return
                if source.agent_session_id != observation.thread:
                    observation.failed(
                        f"SavedThreadSelectionMismatch: requested {observation.thread!r}; "
                        f"selected {source.agent_session_id!r}")
                    return
                transcript = source.presentation.transcript
                if self.transcript is not transcript:
                    self.transcript = transcript
                    observation.subscriptions.enter_context(transcript.events.subscribe(self.event))
                    conversation = source.presentation.widget
                    if conversation is not None:
                        observation.subscriptions.enter_context(
                            conversation.core_publications.subscribe(self.event))
                agent = source.presentation.operational_agent
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
                observation.failed(f'{event.message}: {event.details}')

        with ExitStack() as self.subscriptions:
            events = Events()
            self.subscriptions.enter_context(self.app.events.subscribe(events.event))
            events.selected()
            await self.completed


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
            while not (children := process.children()):
                if terminal.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f'SavedThreadOpenFailed: {thread}; see {output / "st.log"}')
                time.sleep(0.1)
            child, = children
            targets = output / 'targets.json'
            attempt = 0
            while True:
                attempt += 1
                remote = output / f'capture-{attempt}.py'
                status = output / f'capture-{attempt}.status'
                remote.write_text(f'''import sys
_ready = (hasattr(sys.modules.get("pathlib"), "PurePosixPath")
          and hasattr(sys.modules.get("textual.app"), "App")
          and hasattr(sys.modules.get("toad.app"), "ToadApp"))
if _ready:
    from textual._context import NoActiveAppError
    try:
        sys.modules["textual.app"].App.running_app()
    except NoActiveAppError:
        _ready = False
if not _ready:
    open({str(status)!r}, "w").write("not-ready")
else:
    import json, traceback
    try:
        sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
        from build_runtime import install_saved_thread_observer
        install_saved_thread_observer({child.pid}, {thread!r}, {str(targets)!r})
    except BaseException:
        open({str(targets)!r}, "w").write(json.dumps({{"error": traceback.format_exc()}}))
    open({str(status)!r}, "w").write("installed")
''')
                try:
                    sys.remote_exec(child.pid, str(remote))
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
