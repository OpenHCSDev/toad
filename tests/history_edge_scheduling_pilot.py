"""Original wire reads cannot borrow native receipt publication custody.

One actual application journey controls completion of its original source read;
all pages, registrations, messages, read witnesses and native rows remain real.
"""

import asyncio
import importlib.util
import json
import shlex
import sys
import time
import traceback
import os
from pathlib import Path
from functools import partial
from threading import Event
import tempfile
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.thread_execution import ExternalThreadExecution
from agent_comms.comms import wire
from toad.app import ToadApp
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.transcript_history import TranscriptHistory
from toad.transcript_preparation import PageRequest
sys.path.insert(0, str(Path(__file__).resolve().parent / 'tools'))
from record_installed_tui import (ObserveJourney, InputWarmJourney, ProcessOwner,
                                 marker_command, phase_events, main as record_main)


async def until(condition):
    async with asyncio.timeout(8):
        while not condition():
            await asyncio.sleep(.01)


async def pending_read(chat, pilot, body):
    """Control original read completion, never its decoded result or UI state."""
    history = chat.message_history
    reader = history.reader
    entered, release = Event(), Event()
    original = reader.comms.views.channel_display_page

    def read(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        if not release.wait(8):
            raise TimeoutError("Original source completion was not released")
        return result

    with patch.object(reader.comms.views, 'channel_display_page', read):
        await until(lambda: history.state.accepts_source_work)
        refresh = await chat._refresh()
        assert refresh is not None, "The original pager must admit the controlled read"
        try:
            await until(entered.is_set)
            assert not history.state.accepts_source_work
            assert reader._pending, "Actual source I/O must still own its reader task"
            assert not chat.window.history_lock.locked()
            chat.prompt.text = body
            chat.prompt.prompt_text_area.focus()
            await pilot.press('enter')
            await until(lambda: any(m.body == body for m, _ in history.rows)
                        and not chat._human_admission_blocked)
            receipt = next(m for m, _ in history.rows if m.body == body)
            assert not release.is_set()
            assert reader._pending and not refresh.is_finished, (
                "The original read must still be pending when its receipt paints"
            )
            print('receipt visible with original I/O pending', body, flush=True)
            await pilot.pause()
            assert [m.view_key for m, _ in history.rows].count(receipt.view_key) == 1
            widget = next(w for m, w in history.rows if m.view_key == receipt.view_key)
            assert widget.is_attached and widget in chat.screen._compositor.visible_widgets
            chat.prompt.focus()
            await pilot.press('h', 'i')
            assert chat.prompt.text.endswith('hi')
            assert reader._pending and not refresh.is_finished, (
                "Typing must finish before the controlled original read completes"
            )
        finally:
            release.set()
            await refresh.wait()
        await pilot.pause()
        assert [m.view_key for m, _ in history.rows].count(receipt.view_key) == 1
        assert not chat.window.history_lock.locked()
        await until(lambda: history.state.accepts_source_work)


async def exercise(app, pilot, root):
    await pilot.pause()
    owner = app.selected_mode
    await channel_target('#edge').open(NavigationContext(app, owner, root, 'edge-reader'))
    chat = app.screen.query_one(CommsChatView)
    history = chat.message_history
    await until(lambda: history.checkpoint_available and bool(history.rows))
    await pilot.pause()
    assert history in chat.window.histories
    # Tail replacement started from the original initial source. An
    # already-painted later receipt survives its older read watermark.
    history.reader.restart()
    await pending_read(chat, pilot, 'RECEIPT-DURING-TAIL-READ')

    # Actual earlier pages evict the original tail. A send from that
    # reader position restarts the source and rejects the older read.
    operation = history.reserve_source_work()
    try:
        chat.window.release_anchor()
        async with asyncio.timeout(8):
            while not history.has_newer:
                assert history.has_older, "Original tail must be evicted before source exhaustion"
                chat.window.scroll_home(animate=False, immediate=True)
                await pilot.pause()
                page = await history.reader.page(before=history.rows[0][0].view_cursor, limit=40)
                await history.mount_page(page, older=True)
    finally:
        history.finish_source_work(operation)
    assert history.has_newer
    history.reader.restart()
    await pending_read(chat, pilot, 'RECEIPT-REVOKES-ORIGINAL-READ')
    await until(lambda: history.checkpoint_available)
    assert history.rows[-1][0].body == 'RECEIPT-REVOKES-ORIGINAL-READ'

    chat.window.release_anchor()
    # Each older-page publication preserves the actual reader anchor. A
    # single Home therefore moves one edge, not through the whole source.
    # Repeat movement as the user does until the real tail is unmounted.
    async with asyncio.timeout(8):
        while not history.has_newer:
            chat.window.scroll_home(animate=False, immediate=True)
            await pilot.pause(.05)
    chat.window.focus()
    await pilot.press('end')
    # Source completion precedes the native layout that applies its anchor.
    # Require the original Window's settled destination, not just read status.
    await until(lambda: history.checkpoint_available and not history.has_newer
                and chat.window.follows_tail)
    await pilot.pause()
    assert history.rows[-1][0].body == 'RECEIPT-REVOKES-ORIGINAL-READ'
    assert chat.window.follows_tail, "End must retain the original Window's tail anchor"
    assert app._exception is None, repr(app._exception)
    print('PASS: receipt/typing/restart/End on original native window', flush=True)
    return history


def seed_channel(comms, project):
    """Seed fresh wire originals in the existing fixture's private bus."""
    comms.registry.declare(Thread('edge-reader', frozenset({'edge'}), str(project),
                                 process_identity=ProcessIdentity.capture(os.getpid()),
                                 execution=ExternalThreadExecution))
    for index in range(140):
        comms.messaging.send('edge-reader', '#edge', f'History {index}: ' + 'body ' * 40)


async def exercise_with_evidence(app, pilot, root, *, journey=exercise):
    """One acceptance and failure-export lifetime for both physical entries."""
    try:
        history = await journey(app, pilot, root)
    except BaseException as error:
        outcome = {'status': 'failed', 'error': repr(error),
                   'traceback': traceback.format_exc(),
                   'application_exception': repr(app._exception)}
        exporter = Path(__file__).resolve().parents[1] / 'tools/performance/capture_state.py'
        spec = importlib.util.spec_from_file_location('history_failure_capture', exporter)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.capture(expected_pid=os.getpid(), output_prefix=root / 'failed-history-state')
        raise
    else:
        outcome = {'status': 'passed',
            'scope': 'original I/O-held receipt/restart/typing/End assertions completed'}
        return history
    finally:
        pending = root / 'journey-result.pending'
        pending.write_text(json.dumps(outcome) + '\n')
        pending.replace(root / 'journey-result.json')


async def exercise_retained(app, pilot, root):
    keys = ProcessOwner()
    try:
        await exercise_native_destination(
            app, pilot, root, press=partial(HistorySourceLifetimeJourney.press, keys),
        )
        return await exercise(app, pilot, root)
    finally:
        cleanup = await asyncio.to_thread(keys.cleanup)
        (root / 'destination-key-cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n')
        assert not cleanup['remaining_owned_pids'] and not cleanup['errors'], cleanup


async def exercise_native_destination(app, pilot, root, *, press):
    """Use the copied original native source, not a synthetic transcript page."""
    view = app.selected_session.conversation
    window = view.window
    await until(lambda: view.agent_ready and bool(window.histories))
    window.focus()
    async with asyncio.timeout(8):
        while not any(history.has_newer for history in window.histories):
            await press('Home')
            await asyncio.sleep(.05)
    history = next(history for history in window.histories if history.has_newer)
    assert isinstance(history, TranscriptHistory) and history.loader is not None
    await until(lambda: history.state.accepts_source_work)
    reader = history._reader()
    destination = PageRequest(before=history.through)
    entered, release = asyncio.Event(), asyncio.Event()
    original = reader.get

    async def held_read(request):
        prepared = await original(request)
        # The prepared source also serves ordinary edge and lookahead reads.
        # Hold only the original destination request, not whichever read wins
        # the scheduling race after the physical End key.
        if request != destination:
            return prepared
        entered.set()
        await release.wait()
        return prepared

    with patch.object(reader, 'get', held_read):
        window.focus()
        try:
            await press('End')
            await until(entered.is_set)
            operation = history.state
            assert not operation.accepts_source_work
            # Native End deliberately focuses the editor. Restore the original
            # scroll target before the user's revoking Home key.
            window.focus()
            await until(lambda: app.focused is window)
            await press('Home')
            await until(lambda: not window.follows_tail)
            revoked_revision = window.scroll_revision
            assert not window.follows_tail
        finally:
            release.set()
        await until(lambda: history.state is not operation)
        assert window.scroll_revision == revoked_revision and not window.follows_tail, (
            "Native destination revocation changed during source completion",
            revoked_revision, window.scroll_revision, window.follows_tail,
        )
    window.focus()
    await until(lambda: app.focused is window)
    await press('End')
    await until(lambda: history.checkpoint_available and not history.has_newer
                and window.follows_tail)
    await pilot.pause()
    assert app._exception is None, repr(app._exception)
    app.save_screenshot(str(root / 'native-end.svg'))
    (root / 'native-end.json').write_text(json.dumps({
        'source': view.agent.session_id, 'revoked_revision': revoked_revision,
        'monotonic': time.monotonic(),
        'final_revision': window.scroll_revision, 'follows_tail': window.follows_tail,
        'has_newer': history.has_newer, 'application_exception': repr(app._exception),
        'provider_inputs': 0,
        'boundary': 'installed copied original native ACP source, actual End/Home/End keys',
    }, indent=2) + '\n')
    print('PASS: original native End/Home revocation and final End', flush=True)


async def main():
    scratch = Path(__file__).resolve().parents[1] / '.artifacts' / 'history-lifetime338'
    scratch.mkdir(parents=True, exist_ok=True)
    directory = os.environ.get('TOAD_HISTORY_LIFETIME_DIRECTORY') or tempfile.mkdtemp(prefix='private-', dir=scratch)
    root = Path(directory)
    if not root.resolve().is_relative_to(scratch.resolve()):
        raise ValueError('History fixture must use its owned persistent scratch directory')
    root.mkdir(parents=True, exist_ok=True)
    os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'), XDG_CONFIG_HOME=str(root / 'config'),
                      XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'))
    comms = wire(root / 'wire')
    await asyncio.to_thread(seed_channel, comms, root)
    app = ToadApp(project_dir=str(root))
    headless = os.environ.get('L0A_HEADLESS', '1') != '0'
    async with app.run_test(headless=headless, size=(100, 32)) as pilot:
        history = await exercise_with_evidence(app, pilot, root)
        if not headless:
            # The existing recorder owns the physical window and quits through
            # its real Ctrl+Q binding after retaining the visible final frame.
            while not app._exit:
                await asyncio.sleep(.05)
    assert not history.reader._pending
    print('PASS: original read admission, independent receipt paint, typing, restart fence, shared End and closed I/O')


class HistorySourceLifetimeJourney(ObserveJourney):
    """The existing recorder waits for its source fixture's actual outcome."""

    @classmethod
    async def press(cls, owner, *keys):
        # The recorder already owns the isolated display and focused st window.
        # A physical key does not promise that unrelated widget queues or all
        # animations are idle while the original source read is held.
        await asyncio.to_thread(owner.run, ['xdotool', 'key', *keys],
                                os.environ.copy(), timeout=8)

    @classmethod
    def script(cls, args):
        return marker_command() + 'source-start\nexec --sync ' + shlex.join([sys.executable, str(Path(__file__).resolve()),
            '--await-completion', os.environ['TOAD_HISTORY_LIFETIME_DIRECTORY']]) + '\n'


class RetainedHistorySourceJourney(InputWarmJourney):
    """Warm native motion and wire receipt lifetime in one original App."""

    review_artifacts = (*InputWarmJourney.review_artifacts,
                        'history-source-lifetime-review.json')

    @classmethod
    def history_thread(cls, args):
        return 'resource436'

    @classmethod
    def closing_commands(cls, args):
        return (HistorySourceLifetimeJourney.script(args).strip(),
                marker_command() + 'source-complete')

    @classmethod
    def review(cls, output, receipt):
        result = super().review(output, receipt)
        outcome = json.loads((Path(os.environ['TOAD_HISTORY_LIFETIME_DIRECTORY'])
                              / 'journey-result.json').read_text())
        result['source_lifetime'] = outcome
        (output / 'history-source-lifetime-review.json').write_text(json.dumps(outcome) + '\n')
        return result

    @classmethod
    def validate_review(cls, review):
        super().validate_review(review)
        if review['source_lifetime']['status'] != 'passed':
            raise RuntimeError('Original held-reader receipt/End acceptance failed')


async def retained_app(project):
    """The source-entry wrapper imports the selected installed product only."""
    from toad.agent_schema import AgentDefinition

    definition = AgentDefinition(identity='real-resource436', name='Real resource acceptance',
        short_name='resource', run_command={'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])})
    app = ToadApp(agent_data=definition, project_dir=str(project), agent_session_id='resource436')
    root = Path(os.environ['TOAD_HISTORY_LIFETIME_DIRECTORY'])
    output = Path(os.environ['TOAD_VIDEO_OUTPUT'])
    async with app.run_test(headless=False, size=(160, 44)) as pilot:
        # The original marker is appended only after its native screenshot and
        # DTO have completed. Do not race Pilot input with the recorder's keys.
        # The recorder's original ProcessOwner already bounds this child. Its
        # action deadline is established after launch and is not inherited by
        # the UI. The product App retires its own resources; test sibling
        # teardown must never kill the recorder, Xvfb or physical key driver.
        while not any(event['label'] == 'source-start' for event in phase_events(output)):
            await asyncio.sleep(.05)
        history = await exercise_with_evidence(app, pilot, root, journey=exercise_retained)
        while not app._exit:
            await asyncio.sleep(.05)
    assert not history.reader._pending


async def record_retained(service, project, evidence, environment, *, recording_args,
                          recording_timeout, recording_output,
                          journey=RetainedHistorySourceJourney):
    """Existing original-turn fixture callback; owns no second App or root."""
    # These are retained fixture inputs, not actions in the measured journey.
    # Populate the original bus before its App starts observing publication.
    await asyncio.to_thread(seed_channel, service, project)
    env = dict(environment, L0A_HEADLESS='0', TOAD_HISTORY_LIFETIME_DIRECTORY=str(project),
               XDG_STATE_HOME=str(evidence / 'ui-state'))
    env.pop('NO_COLOR', None)
    runtime = Path(sys.executable).parent
    env['AGENT_COMMS_RUNTIME_ROOT'] = str(runtime)
    command = [sys.executable, str(Path(__file__).resolve()), '--record', *recording_args,
        '--capture-target', 'source', '--private-root', str(service.root),
        '--journey', journey.declared_name, '--peer-thread', 'resource236b',
        '--capture-state', '--scroll-travel', '--output', str(recording_output),
        '--', sys.executable, str(Path(__file__).resolve()), '--retained-app', str(project)]
    (evidence / 'joint-command.json').write_text(json.dumps(command, indent=2) + '\n')
    owner = ProcessOwner(service.registry)
    try:
        with (evidence / 'joint-recorder.log').open('w') as log:
            # Both the recording budget and bounded child custody are chosen
            # by its sole installed operator; this callback changes neither.
            await asyncio.to_thread(owner.run, command, env, timeout=recording_timeout,
                                    stdout=log, stderr=log)
    finally:
        cleanup = await asyncio.to_thread(owner.cleanup)
        (evidence / 'joint-cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n')
    assert not cleanup['remaining_owned_pids'] and not cleanup['errors'], cleanup


def await_completion(root):
    """Observe immutable fixture completion, never backend or UI state."""
    deadline = float(os.environ['TOAD_VIDEO_DEADLINE'])
    result = root / 'journey-result.json'
    while not result.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('Original source fixture did not complete within recorder custody')
        time.sleep(.05)
    outcome = json.loads(result.read_text())
    if outcome['status'] != 'passed':
        raise RuntimeError('Original source fixture failed: ' + outcome['error'])


if __name__ == '__main__':
    if sys.argv[1:2] == ['--await-completion']:
        await_completion(Path(sys.argv[2]))
    elif sys.argv[1:2] == ['--retained-app']:
        asyncio.run(retained_app(Path(sys.argv[2])))
    elif sys.argv[1:2] == ['--record']:
        del sys.argv[1]
        record_main()
    else:
        asyncio.run(main())
