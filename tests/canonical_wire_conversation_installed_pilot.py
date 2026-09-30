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

from agent_comms.threads import Thread
from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.native_runtime_input import NativeRuntimeInput
from agent_comms.coordination_tables.assignments import WakeAssignment
from agent_comms.coordination_tables.responses import ResponseObligation
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp as FixtureApp
from toad.app import ToadApp
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.outgoing_message import OutgoingMessage
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.user_input import UserInput
from toad.widgets.agent_response import AgentResponse


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
    if any('IGNORE' in str(message.get('content')) and 'FULL' in str(message.get('content'))
           for message in messages):
        decision = 'FULL' if 'HOT_ORIGINAL_WIRE_BODY' in str(messages[-1]['content']) else 'IGNORE'
        return {'role': 'assistant', 'content': json.dumps({'decision': decision})}, 'stop'
    last = messages[-1]
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


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    recipient = app.selected_session.conversation
    sender_app = WindowApp(agent_data=app.agent_data, project_dir=str(app.project_dir),
                           agent_session_id='alpha')
    irc_app = WindowApp(project_dir=str(app.project_dir))
    evidence = Path(os.environ['L0A_EVIDENCE'])
    async with sender_app.run_test(size=(160, 44)) as sender_pilot:
        sender = sender_app.selected_session.conversation
        await until(sender_pilot, lambda: sender.agent is not None and sender.agent_ready)
        await until(sender_pilot, sender.agent.session.settled.is_set)
        assert sender.agent.session.connected
        async with irc_app.run_test(size=(160, 44)) as irc_pilot:
            await irc_pilot.pause()
            user = comms.messaging.user_identity(str(app.project_dir)).name
            await channel_target('#team').open(NavigationContext(
                irc_app, irc_app.selected_mode, app.project_dir, user))
            await irc_app.selected_session.wait_content_ready()
            irc = irc_app.selected_session.query_one(CommsChatView)
            await until(irc_pilot, lambda: irc.message_history.initialized)
            # All three windows are already open before the native send.
            sender.prompt.text = 'HOT_ORIGINAL_TRIGGER'
            sender.prompt.prompt_text_area.focus()
            await sender_pilot.press('enter')
            await until(sender_pilot, lambda: any(m.body == '@beta HOT_ORIGINAL_WIRE_BODY'
                        for m in comms.bus.log.full_history()), 30)
            original = next(m for m in comms.bus.log.full_history()
                            if m.body == '@beta HOT_ORIGINAL_WIRE_BODY')
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
            native_reply_proof = original_native_reply_proof(comms, original, response)
            evidence.joinpath('original-native-reply-proof.json').write_text(
                json.dumps(native_reply_proof, indent=2))
            await until(pilot, lambda: not comms.registry.require('beta').executing)
            # Additional real channel inputs may legitimately move this reply
            # off the tail. Navigate its original body before requiring paint.
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
                app.save_screenshot(str(evidence / 'recipient-reply.svg'))
                print('RECIPIENT_REPLY_RESOURCE_COUNT',
                      sum(body.source == response.body for body in bodies), flush=True)
            assert sum(body.source == response.body for body in bodies) == 1, \
                'Original recipient reply must have exactly one rendered body'
            print('THREE_OPEN_WINDOWS_ORIGINAL_OUTBOUND_INBOUND_TARGET_RESPONDED_HOT', flush=True)
            for name, window in (('sender', sender_app), ('recipient', app), ('irc', irc_app)):
                window.save_screenshot(str(evidence / f'{name}.svg'))
                assert window._exception is None
            # Actual A/B/A tab clicks retain the original source mapping.
            first = sender_app.selected_session
            await channel_target('#team').open(NavigationContext(
                sender_app, sender_app.selected_mode, app.project_dir, user))
            await sender_app.selected_session.wait_content_ready()
            label = next(item for item in sender_app.screen.query(SessionLabel) if item.id == first.id)
            label.scroll_visible(animate=False, immediate=True)
            await sender_pilot.pause()
            assert await sender_pilot.click(label, offset=(label.size.width // 2, 0))
            await until(sender_pilot, lambda: sender_app.selected_session is first)
            await until(sender_pilot, lambda: len(originals(first.conversation, original.reference, OutgoingMessage)) == 1)
            assert 'Responded' in str(originals(first.conversation, original.reference, OutgoingMessage)[0].query_one(MessageNotifications).title)
            # The ordinary prompt also has one original native input after return.
            assert sum(body.content == 'HOT_ORIGINAL_TRIGGER'
                       for body in first.conversation.contents.query(UserInput)) == 1
            print('PHYSICAL_RETURN_ORIGINAL_ROWS_HANDLING_AND_STARTED_INPUT_ONCE', flush=True)
            # A fresh window reads the same original source without sending or
            # relaying an input. The existing owner remains the process owner.
            cold_app = WindowApp(agent_data=app.agent_data, project_dir=str(app.project_dir),
                                 agent_session_id='alpha')
            async with cold_app.run_test(size=(160, 44)) as cold_pilot:
                cold = cold_app.selected_session.conversation
                await until(cold_pilot, lambda: cold.agent is not None and cold.agent_ready)
                await until(cold_pilot, cold.agent.session.settled.is_set)
                assert cold.agent.session.connected
                await until(cold_pilot, lambda: len(originals(cold, original.reference, OutgoingMessage)) == 1)
                await until(cold_pilot, lambda: len(originals(cold, response.reference, IncomingMessage)) == 1)
                await until(cold_pilot, lambda: 'Responded' in str(
                    originals(cold, original.reference, OutgoingMessage)[0].query_one(MessageNotifications).title))
                assert sum(body.content == 'HOT_ORIGINAL_TRIGGER'
                           for body in cold.contents.query(UserInput)) == 1
                cold_app.save_screenshot(str(evidence / 'cold-sender.svg'))
                assert cold_app._exception is None
            print('COLD_SOURCE_ORIGINAL_IDENTITIES_AND_HANDLING_ONCE', flush=True)
            evidence.joinpath('receipt.json').write_text(json.dumps({
                'original': {'seq': original.seq, 'id': original.message_id},
                'reply': {'seq': response.seq, 'id': response.message_id},
                'provider_requests': len(requests), 'original_inputs_retried': 0,
                'all_views_open_before_send': True,
                'original_target_handling': 'Responded',
                'original_has_five_newer_channel_inputs': True,
                'original_native_reply': native_reply_proof,
                'public_cursor': FieldCodec.encode(agent._private_cursor.current),
                'cold_source_once': True,
            }, indent=2))


if __name__ == '__main__':
    asyncio.run(main(app_type=EvidenceApp, prepare_state=prepare, acceptance=acceptance, provider_reply=reply,
                     provider_request_budget=12))
