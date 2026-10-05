"""Continuous installed sender/recipient/IRC publication of original wire facts.

Only the loopback provider is controlled. Three real Toad windows, ACP clients,
native owners, journal source, durable wire, assignment state and UI preparation
remain the application path. No application state or message delivery is mocked.
"""

import asyncio
import json
import os
from pathlib import Path
from threading import Event
from contextlib import asynccontextmanager
import shutil
import shlex
import stat
import sqlite3
import time
import sys
import hashlib

from agent_comms.threads import Thread
from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.native_runtime_input import NativeRuntimeInput
from agent_comms.transcript_events import WireTextTranscript, UserTranscript
from agent_comms.coordination_tables.assignments import WakeAssignment
from agent_comms.coordination_tables.responses import ResponseObligation
from l0a_native_installed_pilot import main, until as native_until, response_painted, selected_triage_reply
from agent_comms.selected_triage import FullSelectedTriage, IgnoreSelectedTriage
from runtime_fixture import ToadApp as FixtureApp
from toad.app import ToadApp
from toad.navigation_target import NavigationContext, channel_target, ThreadTarget
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.outgoing_message import OutgoingMessage
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.user_input import UserInput
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import MessageDivider
from toad.widgets.transcript_history import TranscriptHistory
from toad.agent_schema import AgentDefinition


async def until(pilot, predicate, seconds=20):
    """Invoke the existing driver in its actual Textual window's context."""
    with pilot.app._context():
        return await native_until(pilot, predicate, seconds)


async def pause(pilot, delay=None):
    with pilot.app._context():
        await pilot.pause(delay)


async def select_window(pilot, screen):
    with pilot.app._context():
        label = next(label for label in pilot.app.screen.query(SessionLabel) if label.id == screen.id)
        label.scroll_visible(animate=False, immediate=True)
        await pause(pilot)
        began = time.monotonic()
        assert await pilot.click(label, offset=(label.size.width // 2, 0))
        await until(pilot, lambda: pilot.app.selected_session is screen)
        return began


def record_phase(receipt, evidence, phase):
    receipt['phase'] = phase
    (evidence / 'progress.json').write_text(json.dumps(receipt, indent=2))
    print('CONTROLLED_JOURNEY_PHASE', phase, flush=True)


class WindowApp(ToadApp):
    CSS_PATH = FixtureApp.CSS_PATH


class EvidenceApp(FixtureApp):
    @asynccontextmanager
    async def run_test(self, **kwargs):
        service = wire(os.environ['AGENT_COMMS_ROOT'])
        try:
            async with super().run_test(**kwargs) as pilot:
                yield pilot
        finally:
            sender_release.set()
            recipient_release.set()
            evidence = Path(os.environ['L0A_EVIDENCE'])
            for thread in service.registry.all_threads().values():
                if thread.session_file and Path(thread.session_file).exists():
                    shutil.copyfile(thread.session_file, evidence / f'native-{thread.name}.jsonl')
            evidence.joinpath('original-wire.json').write_text(json.dumps(
                [message.to_wire() for message in service.bus.log.full_history()], indent=2))
            # Retain original coordinator/native input proof, including selected
            # journals that are not the ordinary registration.session_file.
            def resources_only(directory, names):
                return [name for name in names if not (
                    stat.S_ISREG((Path(directory) / name).lstat().st_mode)
                    or stat.S_ISDIR((Path(directory) / name).lstat().st_mode))]
            shutil.copytree(service.root, evidence / 'canonical-wire', ignore=resources_only)
            shutil.copytree(Path(os.environ['PI_CODING_AGENT_DIR']),
                            evidence / 'native-config-and-journals', ignore=resources_only)


recipient_entered, recipient_release = Event(), Event()
sender_entered, sender_release = Event(), Event()


async def prepare(comms, project, requests, entered, release, hold_next):
    release.set()
    hold_next.clear()
    package = Path(os.environ['AC_NATIVE_COPIED_PACKAGE'])
    os.environ['AGENT_COMMS_AGENT_ARGS'] = shlex.join([
        '--provider', 'selected-offline', '--model', 'fixture', '--no-extensions',
        '--no-skills', '--no-context-files', '--no-builtin-tools',
        '--extension', str(package / 'agent-comms-extensions/global-agent-comms/index.mjs'),
    ])
    comms.registry.declare(Thread('alpha', frozenset({'team'}), str(project),
                                  model='selected-offline/fixture', thinking_level='off'))
    await asyncio.to_thread(comms.owners.start, 'alpha')


def reply(request, number):
    messages = request['messages']
    decision = (FullSelectedTriage() if 'HOT_ORIGINAL_WIRE_BODY' in str(messages[-1]['content'])
                else IgnoreSelectedTriage())
    if (triage := selected_triage_reply(request, decision)) is not None:
        return triage, 'stop'
    last = messages[-1]
    if last['role'] == 'user' and 'CONTROLLED_RETURN_' in str(last['content']):
        text = str(last['content'])
        token = next(f'CONTROLLED_RETURN_{index}' for index in range(3)
                     if f'CONTROLLED_RETURN_{index}' in text)
        return {'role': 'assistant', 'content': token}, 'stop'
    if last['role'] == 'user' and 'HOT_ORIGINAL_TRIGGER' in str(last['content']):
        return {'role': 'assistant', 'tool_calls': [{
            'index': 0, 'id': 'hot-original-send', 'type': 'function',
            'function': {'name': 'comms_send', 'arguments': json.dumps({
                'from': 'alpha', 'to': '#team', 'body': '@beta HOT_ORIGINAL_WIRE_BODY',
            })},
        }]}, 'tool_calls'
    if last['role'] == 'tool':
        sender_entered.set()
        assert sender_release.wait(20), 'Open sender view did not release its provider'
        text = 'SENDER_SENT_CONFIRMATION'
    else:
        recipient_entered.set()
        assert recipient_release.wait(20), 'Open recipient view did not release its provider'
        text = 'RECIPIENT_RESPONSE_PROOF'
    return {'role': 'assistant', 'content': text}, 'stop'


def originals(view, reference, kind):
    return [body for body in view.contents.query(kind)
            if body.message_reference == reference]


def original_observation(view, reference, kind):
    """Read existing source and presentation owners before any assertion."""
    histories = tuple(view.window.histories)
    return {'view_attached': view.is_attached,
            'view_is_selected': view.app.selected_session.conversation is view,
            'mounted_count': len(originals(view, reference, kind)),
            'mounted_rows': [{'resource_id': id(body),
                              'ancestors': [{'kind': type(parent).__name__, 'resource_id': id(parent)}
                                            for parent in body.ancestors],
                              'history_resources': [
                                  {'resource_id': id(parent), 'registered_here': parent in histories,
                                   'window_resource_id': id(parent.window),
                                   'current_window_resource_id': id(view.window),
                                   'cursor': FieldCodec.encode(parent.committed_cursor)}
                                  for parent in body.ancestors if isinstance(parent, TranscriptHistory)],
                              'region': str(body.region),
                              'painted': body in view.screen._compositor.visible_widgets,
                              'in_viewport': body.region.overlaps(view.window.region)}
                             for body in originals(view, reference, kind)],
            'source_events': [
                {'history': type(history).__name__,
                 'resource_id': id(history),
                 'cursor': FieldCodec.encode(history.committed_cursor),
                 'resident_pages': [
                     {'before': FieldCodec.encode(page.page.before),
                      'after': FieldCodec.encode(page.page.after),
                      'first_fragment': page.start, 'last_fragment': page.stop,
                      'fragment_count': len(page.fragments)}
                     for page in history.pages],
                 'matching_events': [type(event).__name__ for event in history.coverage_events
                                     if isinstance(event, WireTextTranscript)
                                     and event.source == reference]}
                for history in histories]}


def original_native_reply_proof(comms, original, response):
    """Read the original typed rows, never infer provenance from reply text."""
    database = comms.root / 'coordination.sqlite3'
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        claims = WakeAssignment.select(db, where='wire_seq=? AND message_id=? AND recipient=?',
                                       parameters=(original.seq, original.message_id, 'beta'))
        assert len(claims) == 1
        claim = claims[0]
        inputs = NativeRuntimeInput.select(db, where='assignment_id=? AND stage=?',
                                           parameters=(claim.assignment_id, 'full'))
        assert len(inputs) == 1
        native = inputs[0]
        assert native.owner_lookup == claim.recipient_lookup
        assert native.session_entry_id is not None
        obligations = ResponseObligation.select(db, where='execution_id=?',
                                                parameters=(native.execution_id,))
        assert len(obligations) == 1
        published = obligations[0].lifecycle
        assert (published.receipt_seq, published.receipt_message_id) == (
            response.seq, response.message_id)
        return {'assignment_id': claim.assignment_id,
                'recipient_lookup': claim.recipient_lookup,
                'native_input_id': native.input_id,
                'execution_id': native.execution_id,
                'native_entry_id': native.session_entry_id,
                'native_session_file': native.session_file}


async def cold_source_acceptance(app, pilot, comms, original, response, receipt, evidence):
    """Inspect the original source, then bring its native user into the viewport."""
    cold = app.selected_session.conversation
    await until(pilot, lambda: cold.agent is not None and cold.agent_ready)
    await until(pilot, cold.agent.session.settled.is_set)
    assert cold.agent.session.connected
    await until(pilot, lambda: len(originals(cold, original.reference, OutgoingMessage)) == 1)
    await until(pilot, lambda: len(originals(cold, response.reference, IncomingMessage)) == 1)
    await until(pilot, lambda: 'Responded' in str(
        originals(cold, original.reference, OutgoingMessage)[0].query_one(MessageNotifications).title))
    page = await cold.agent.get_transcript_page()
    users = [event for event in page.events if isinstance(event, UserTranscript)
             and event.text == 'HOT_ORIGINAL_TRIGGER']
    assert len(users) == 1
    native_id = users[0].native_id
    assert native_id is not None

    def user_bodies():
        from toad.widgets.committed_presentation import NativeInputClaim
        return [body for body in cold.contents.query(UserInput)
                if isinstance(body.commit_claim, NativeInputClaim)
                and body.commit_claim.native_id == native_id]

    with app._context():
        receipt['cold_before_scroll'] = {
            'canonical_user': FieldCodec.encode(users[0]),
            'mounted_user_count': len(user_bodies()),
            'original_resource': original_observation(cold, original.reference, OutgoingMessage),
            'categories': [category.declared_name for category in cold.visible_categories],
        }
        app.save_screenshot(str(evidence / 'cold-before-scroll.svg'))
    record_phase(receipt, evidence, 'cold_source_before_scroll')
    with app._context():
        cold.window.focus()
        await pilot.press('home')
    await until(pilot, lambda: len(user_bodies()) == 1)
    with app._context():
        user_bodies()[0].scroll_visible(animate=False, immediate=True)

    def original_user_painted():
        body = user_bodies()[0]
        viewport = cold.window.region
        frame = '\n'.join(strip.crop(viewport.x, viewport.right).text
                          for strip in app.screen._compositor.render_strips()[viewport.y:viewport.bottom])
        return (body in app.screen._compositor.visible_widgets
                and body.region.overlaps(viewport) and users[0].text in frame)

    await until(pilot, original_user_painted)
    with app._context():
        body = user_bodies()[0]
        receipt['cold_after_scroll'] = {
            'native_id': body.commit_claim.native_id, 'mounted_user_count': len(user_bodies()),
            'region': str(body.region), 'painted': original_user_painted(),
            'original_resource': original_observation(cold, original.reference, OutgoingMessage),
        }
        app.save_screenshot(str(evidence / 'cold-sender.svg'))
    record_phase(receipt, evidence, 'cold_source_painted_once')
    assert app._exception is None


async def readonly_cold_main():
    """Continue only the missing cold/retirement check on an existing test root."""
    from runtime_fixture import stop_test_owners, stop_test_children
    stage = Path(os.environ['AC_CONTROLLED_READONLY_STAGE'])
    assert stage.is_relative_to('/home/ts/wt')
    comms = wire(os.environ['AGENT_COMMS_ROOT'])
    assert comms.root == stage / 'private-root/wire'
    assert all(not thread.process_alive and not thread.executing
               for thread in comms.registry.all_threads().values())
    messages = comms.bus.log.full_history()
    original = next(message for message in messages if message.body == '@beta HOT_ORIGINAL_WIRE_BODY')
    response = next(message for message in messages if message.body == 'RECIPIENT_RESPONSE_PROOF')
    native_files = tuple((stage / 'application/pi').rglob('*.jsonl')) + tuple(
        (comms.root / 'native-sessions').rglob('*.jsonl'))
    before_native = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in native_files}
    with sqlite3.connect((comms.root / 'coordination.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        before_inputs = tuple(row[0] for row in db.execute('SELECT input_id FROM native_runtime_input ORDER BY input_id'))
    definition = AgentDefinition.decode({
        'name': 'Native fixture', 'identity': 'native-fixture', 'short_name': 'native',
        'protocol': 'acp', 'run_command': {'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])},
    })
    app = WindowApp(agent_data=definition, project_dir=str(stage / 'application/project'), agent_session_id='alpha')
    evidence = Path(os.environ['L0A_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=False)
    receipt = {'original_inputs_retried': 0, 'inputs_sent': 0, 'native_input_ids_before': before_inputs}
    try:
        # The completed test deliberately stopped its owned daemon. Read-only
        # continuation explicitly starts that fixture owner, never an input.
        await asyncio.to_thread(comms.owners.start, 'alpha')
        async with app.run_test(size=(160, 44)) as pilot:
            await cold_source_acceptance(app, pilot, comms, original, response, receipt, evidence)
        receipt['application_shutdown'] = True
    except BaseException:
        import traceback
        (evidence / 'failure.txt').write_text(traceback.format_exc())
        raise
    finally:
        await asyncio.to_thread(stop_test_owners, comms.root)
        await stop_test_children(os.environ.get('TOAD_TEST_ATTEMPT'))
    with sqlite3.connect((comms.root / 'coordination.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        after_inputs = tuple(row[0] for row in db.execute('SELECT input_id FROM native_runtime_input ORDER BY input_id'))
    receipt['native_input_ids_after'] = after_inputs
    receipt['native_journals_unchanged'] = all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before_native.items())
    assert after_inputs == before_inputs
    assert receipt['native_journals_unchanged']
    assert all(not thread.process_alive for thread in comms.registry.all_threads().values())
    receipt['complete'] = True
    record_phase(receipt, evidence, 'readonly_cold_complete')
    (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2))


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    recipient = app.selected_session.conversation
    sender_app = WindowApp(agent_data=app.agent_data, project_dir=str(app.project_dir),
                           agent_session_id='alpha')
    irc_app = WindowApp(project_dir=str(app.project_dir))
    evidence = Path(os.environ['L0A_EVIDENCE'])
    receipt = {'all_views_open_before_send': False, 'original_inputs_retried': 0}
    record_phase(receipt, evidence, 'opening_sender')
    async with sender_app.run_test(size=(160, 44)) as sender_pilot:
        sender = sender_app.selected_session.conversation
        await until(sender_pilot, lambda: sender.agent is not None and sender.agent_ready)
        await until(sender_pilot, sender.agent.session.settled.is_set)
        assert sender.agent.session.connected
        async with irc_app.run_test(size=(160, 44)) as irc_pilot:
            await pause(irc_pilot)
            user = comms.messaging.user_identity(str(app.project_dir)).name
            with irc_app._context():
                await channel_target('#team').open(NavigationContext(
                    irc_app, irc_app.selected_mode, app.project_dir, user))
                await irc_app.selected_session.wait_content_ready()
            irc = irc_app.selected_session.query_one(CommsChatView)
            await until(irc_pilot, lambda: (irc.message_history.reader is not None and not irc.message_history.reader.source.loading))
            # All three windows are already open before the native send.
            receipt['all_views_open_before_send'] = True
            record_phase(receipt, evidence, 'original_send')
            with sender_app._context():
                sender.prompt.text = 'HOT_ORIGINAL_TRIGGER'
                sender.prompt.prompt_text_area.focus()
                await sender_pilot.press('enter')
            await until(sender_pilot, lambda: any(m.body == '@beta HOT_ORIGINAL_WIRE_BODY'
                        for m in comms.bus.log.full_history()), 30)
            original = next(m for m in comms.bus.log.full_history()
                            if m.body == '@beta HOT_ORIGINAL_WIRE_BODY')
            receipt['original'] = FieldCodec.encode(original.reference)
            record_phase(receipt, evidence, 'original_durable')
            await until(sender_pilot, lambda: bool(originals(sender, original.reference, OutgoingMessage)))
            await until(pilot, lambda: bool(originals(recipient, original.reference, IncomingMessage)))
            await until(irc_pilot, lambda: any(m.reference == original.reference
                        for m, _ in irc.message_history.rows))
            sent = originals(sender, original.reference, OutgoingMessage)[0]
            received = originals(recipient, original.reference, IncomingMessage)[0]
            await until(pilot, recipient_entered.is_set)
            await until(sender_pilot, sender_entered.is_set)
            pending = next(item for item in comms.views.message_notifications((original,))[original.seq, original.message_id]
                           if item.recipient == 'beta')
            assert pending.busy, pending
            await until(sender_pilot, lambda: pending.state in str(sent.query_one(MessageNotifications).title))
            await until(pilot, lambda: pending.state in str(received.query_one(MessageNotifications).title))
            assert comms.registry.require('alpha').executing
            print('BOTH_NATIVE_TURNS_HELD_ORIGINAL_ROWS_AND_PROCESSING_HOT', pending.state, flush=True)
            receipt['processing'] = pending.state
            record_phase(receipt, evidence, 'original_processing_hot')
            # Move the original outside the recent-five convenience window
            # while it is still processing. These are real durable channel
            # inputs; the controlled native provider declines their triage.
            for index in range(5):
                await asyncio.to_thread(comms.messaging.send, 'alpha', '#team',
                                        f'AMBIENT_AFTER_ORIGINAL_{index}')
            sender_release.set()
            recipient_release.set()
            await until(sender_pilot, lambda: any(item.recipient == 'beta' and item.state == 'Responded'
                        for item in comms.views.message_notifications((original,))[original.seq, original.message_id]), 30)
            await until(sender_pilot, lambda: 'Responded' in str(sent.query_one(MessageNotifications).title))
            await until(pilot, lambda: 'Responded' in str(received.query_one(MessageNotifications).title))
            row = next(widget for message, widget in irc.message_history.rows
                       if message.reference == original.reference)
            await until(irc_pilot, lambda: 'Responded' in str(row.query_one(MessageNotifications).title))
            assert len(originals(sender, original.reference, OutgoingMessage)) == 1
            assert len(originals(recipient, original.reference, IncomingMessage)) == 1
            response = next(m for m in comms.bus.log.full_history()
                            if m.sender == 'beta' and m.body == 'RECIPIENT_RESPONSE_PROOF')
            await until(pilot, lambda: bool(originals(recipient, response.reference, OutgoingMessage)))
            await until(sender_pilot, lambda: bool(originals(sender, response.reference, IncomingMessage)))
            assert len(originals(recipient, response.reference, OutgoingMessage)) == 1
            assert len(originals(sender, response.reference, IncomingMessage)) == 1
            assert original.reference != response.reference
            receipt['reply'] = FieldCodec.encode(response.reference)
            native_reply_proof = original_native_reply_proof(comms, original, response)
            evidence.joinpath('original-native-reply-proof.json').write_text(
                json.dumps(native_reply_proof, indent=2))
            await until(pilot, lambda: not comms.registry.require('beta').executing)
            # Additional real channel inputs may legitimately move this reply
            # off the tail. Navigate its original body before requiring paint.
            with app._context():
                originals(recipient, response.reference, OutgoingMessage)[0].scroll_visible(
                    animate=False, immediate=True)
            try:
                await until(pilot, lambda: response_painted(app, recipient, response.body))
            finally:
                bodies = tuple(recipient.contents.query(AgentResponse))
                observation = [{'source': body.source, 'attached': body.is_attached,
                                'parent': type(body.parent).__name__}
                               for body in bodies]
                evidence.joinpath('recipient-reply-resources.json').write_text(
                    json.dumps(observation, indent=2))
                with app._context():
                    app.save_screenshot(str(evidence / 'recipient-reply.svg'))
                print('RECIPIENT_REPLY_RESOURCE_COUNT',
                      sum(body.source == response.body for body in bodies), flush=True)
            assert sum(body.source == response.body for body in bodies) == 1, \
                'Original recipient reply must have exactly one rendered body'
            assert len(originals(recipient, response.reference, OutgoingMessage)[0].query(MessageDivider)) == 1
            receipt['original_native_reply'] = native_reply_proof
            receipt['original_target_handling'] = 'Responded'
            record_phase(receipt, evidence, 'hot_handling_reply_once_painted')
            print('THREE_OPEN_WINDOWS_ORIGINAL_OUTBOUND_INBOUND_TARGET_RESPONDED_HOT', flush=True)
            for name, window in (('sender', sender_app), ('recipient', app), ('irc', irc_app)):
                with window._context():
                    window.save_screenshot(str(evidence / f'{name}.svg'))
                assert window._exception is None
            # Keep the same windows open beyond the user's 15–30s recurrence.
            receipt['same_open_31s'] = []
            for second in range(31):
                await pause(pilot, 1)
                counts = {'original_sender': len(originals(sender, original.reference, OutgoingMessage)),
                          'original_recipient': len(originals(recipient, original.reference, IncomingMessage)),
                          'reply_sender': len(originals(recipient, response.reference, OutgoingMessage)),
                          'reply_recipient': len(originals(sender, response.reference, IncomingMessage))}
                receipt['same_open_31s'].append({'second': second, **counts})
                record_phase(receipt, evidence, 'same_open_observation')
                if not all(count == 1 for count in counts.values()):
                    receipt['failed_original_projection'] = {}
                    for name, window, view, kind in (
                        ('sender', sender_app, sender, OutgoingMessage),
                        ('recipient', app, recipient, IncomingMessage)):
                        with window._context():
                            receipt['failed_original_projection'][name] = original_observation(
                                view, original.reference, kind)
                            window.save_screenshot(str(evidence / f'failed-original-{name}.svg'))
                        page = await asyncio.to_thread(comms.transcripts.thread_transcript_page,
                                                       view.agent.session_id)
                        receipt['failed_original_projection'][name]['canonical_page'] = {
                            'before': FieldCodec.encode(page.before),
                            'after': FieldCodec.encode(page.after),
                            'matching_events': [type(event).__name__ for event in page.events
                                                if isinstance(event, WireTextTranscript)
                                                and event.source == original.reference]}
                    record_phase(receipt, evidence, 'original_projection_failure')
                assert all(count == 1 for count in counts.values()), counts
                assert sum(body.source == response.body for body in recipient.contents.query(AgentResponse)) == 1
                assert all(window._exception is None for window in (app, sender_app, irc_app))
            record_phase(receipt, evidence, 'same_open_31s_complete')
            beta_screen = app.selected_session
            with app._context():
                await ThreadTarget('alpha').open(NavigationContext(app, app.selected_mode, app.project_dir, user))
                await app.selected_session.wait_content_ready()
            alpha_screen = app.selected_session
            receipt['physical_return_immediate_send'] = []
            for index, screen in enumerate((beta_screen, alpha_screen, beta_screen)):
                began = await select_window(pilot, screen)
                view = screen.conversation
                await until(pilot, lambda: view.agent is not None and view.agent_ready)
                token = f'CONTROLLED_RETURN_{index}'
                with app._context():
                    view.prompt.text = f'Bounded acceptance only. Reply exactly {token}.'
                    view.prompt.prompt_text_area.focus()
                    await pilot.press('enter')
                record_phase(receipt, evidence, f'physical_return_{index}_input')
                await until(pilot, lambda: sum(body.source == token for body in view.contents.query(AgentResponse)) == 1, 30)
                await until(pilot, lambda: not comms.registry.require(view.agent.session_id).executing)
                receipt['physical_return_immediate_send'].append({
                    'thread': view.agent.session_id, 'reply_seconds': time.monotonic() - began})
                record_phase(receipt, evidence, f'physical_return_{index}_reply')
                with sender_app._context():
                    observed_sender = original_observation(sender, original.reference, OutgoingMessage)
                with app._context():
                    observed_recipient = original_observation(recipient, original.reference, IncomingMessage)
                receipt['physical_return_immediate_send'][-1]['original_views'] = {
                    'sender': observed_sender, 'recipient': observed_recipient}
                record_phase(receipt, evidence, f'physical_return_{index}_original_source')
                await until(sender_pilot, lambda: len(originals(sender, original.reference, OutgoingMessage)) == 1)
                await until(pilot, lambda: len(originals(recipient, original.reference, IncomingMessage)) == 1)
                with app._context():
                    app.save_screenshot(str(evidence / f'physical-return-{index}.svg'))
            assert sum(body.content == 'HOT_ORIGINAL_TRIGGER'
                       for body in sender.contents.query(UserInput)) == 1
            print('PHYSICAL_RETURN_ORIGINAL_ROWS_HANDLING_AND_STARTED_INPUT_ONCE', flush=True)
            # A fresh window reads the same original source without sending or
            # relaying an input. The existing owner remains the process owner.
            cold_app = WindowApp(agent_data=app.agent_data, project_dir=str(app.project_dir),
                                 agent_session_id='alpha')
            async with cold_app.run_test(size=(160, 44)) as cold_pilot:
                await cold_source_acceptance(cold_app, cold_pilot, comms, original, response, receipt, evidence)
            print('COLD_SOURCE_ORIGINAL_IDENTITIES_AND_HANDLING_ONCE', flush=True)
            receipt.update({
                'provider_requests': len(requests), 'original_inputs_retried': 0,
                'all_views_open_before_send': True,
                'original_target_handling': 'Responded',
                'original_has_five_newer_channel_inputs': True,
                'original_native_reply': native_reply_proof,
                'public_cursor': FieldCodec.encode(agent._private_cursor.current),
                'cold_source_once': True, 'complete': True,
            })
            record_phase(receipt, evidence, 'complete')
            evidence.joinpath('receipt.json').write_text(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    if os.environ.get('AC_CONTROLLED_READONLY_STAGE'):
        asyncio.run(readonly_cold_main())
    else:
        asyncio.run(main(app_type=EvidenceApp, prepare_state=prepare, acceptance=acceptance, provider_reply=reply,
                     provider_request_budget=18,
                     fixture_stage=Path(os.environ['AC_CONTROLLED_FIXTURE_STAGE'])))
