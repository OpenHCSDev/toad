"""Old checked channel history must not become new tail input after a cold load."""

import asyncio
import os
import json
import cProfile
import pstats
import shutil
from pathlib import Path
import time

from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.threads import Thread
from l0a_native_installed_pilot import main, until
from inbound_history_reprojection_installed_pilot import send_channel, matching
from receiver_inbound_installed_pilot import paint
from toad.widgets.incoming_message import AssignedIncomingMessage
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity


async def seed_retained_source(comms, package):
    """Create inactive retained history with the actual native journal owner."""
    await asyncio.to_thread(comms.owners.stop, 'beta')
    path = comms.registry.require('beta').session_file
    script = Path(os.environ['L0A_EVIDENCE']).parent / 'seed-retained-source.mjs'
    script.write_text("""
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const [moduleFile, session] = process.argv.slice(2);
const { SessionManager } = await import(pathToFileURL(moduleFile));
const records = fs.readFileSync(session, 'utf8').trim().split('\\n').map(JSON.parse);
const template = records.find(row => row.message?.role === 'assistant').message;
const manager = SessionManager.open(session);
const text = 'RETAINED_OLD_BODY '.repeat(9000);
for (let index = 0; index < 256; index++) {
  manager.appendMessage({...template, content: [{type: 'text', text: text + index}], timestamp: Date.now()});
}
const boundary = manager.appendMessage({role: 'user', content: 'RETAINED_BOUNDARY', timestamp: Date.now()});
manager.appendCompaction('Recorded retained history; resume with the boundary.', boundary, 900000);
console.log(fs.statSync(session).size);
""")
    proc = await asyncio.create_subprocess_exec('node', str(script),
        str(package / 'dist/core/session-manager.js'), path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, error = await proc.communicate()
    assert proc.returncode == 0, error.decode()
    size = int(out)
    assert 40_000_000 <= size <= 50_000_000, size
    print('ACTUAL_NATIVE_RETAINED_SOURCE_BYTES', size, flush=True)
    await asyncio.to_thread(comms.owners.start, 'beta')


class SeedSubscriber:
    async def session_update(self, **kwargs):
        pass


async def prepare(comms, project, requests, entered, release, hold_next):
    package = Path(os.environ['AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE'])
    root_id = os.environ['AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID']
    comms.owners.pin_private_nk_launch(comms.root, root_id, package)
    comms.registry.declare(Thread('sender', frozenset({'team'}), str(project)))
    release.set()
    hold_next.clear()
    peer = CommsClient(comms, runtime_enabled=True, private_nk_native_package=package,
                       private_nk_wire_root_id=root_id)
    peer.on_connect(SeedSubscriber())
    try:
        await peer.load_session(cwd=str(project), session_id='beta')
        await peer.prompt('beta', [TextContentBlock(type='text', text='NATIVE_BEFORE_OLD_CHANNEL')])
        message = await send_channel(comms, 'OLD_CHECKED_CHANNEL_HISTORY')
        async with asyncio.timeout(30):
            while not any(notice.message is not None and notice.message.seq == message.seq
                          and 'no response' in notice.state.lower()
                          for notice in comms.views.recent_notifications('beta')):
                await asyncio.sleep(.05)
        if os.environ.get('L0A_LARGE_SOURCE'):
            await peer.shutdown()
            await seed_retained_source(comms, package)
            peer = CommsClient(comms, runtime_enabled=True, private_nk_native_package=package,
                               private_nk_wire_root_id=root_id)
            peer.on_connect(SeedSubscriber())
            await peer.load_session(cwd=str(project), session_id='beta')
        await peer.prompt('beta', [TextContentBlock(type='text', text='NATIVE_AFTER_OLD_CHANNEL')])
        assert len(requests) == 3
    finally:
        await peer.shutdown()
    # Genuine saved owner startup precedes the first UI/history mount.
    await asyncio.to_thread(comms.owners.stop, 'beta')
    await asyncio.to_thread(comms.owners.start, 'beta')
    if os.environ.get('L0A_SWITCH_SOURCE'):
        from agent_comms.thread_management import ForkSpec
        await asyncio.to_thread(comms.threads.fork, ForkSpec('alpha', 'beta', prompt=''))
    evidence = Path(os.environ['L0A_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(comms.registry.require('beta').session_file,
                    evidence / 'seeded-retained-native.jsonl')
    print('REAL_NATIVE_HISTORY_AND_IGNORED_CHANNEL_SEEDED_OWNER_RESTARTED', flush=True)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    message = next(notice.message for notice in comms.views.recent_notifications('beta')
                   if notice.message is not None and notice.message.body == 'OLD_CHECKED_CHANNEL_HISTORY')
    observed = view.query_one(ObservedThreadActivity)
    started = time.monotonic()
    appearances = []
    # Keep the SAME open view through the user's full 15–30 second interval.
    # There are no reconnects, tab switches or additional inputs in this interval.
    for second in range(31):
        appearances.append((round(time.monotonic()-started, 2),
                            len(matching(view, message.seq)),
                            sum(isinstance(child, AssignedIncomingMessage) and child.sequence == message.seq
                                for child in view.contents.children)))
        await pilot.pause(1)
    print('SAME_OPEN_30_SECOND_INBOUND_TIMELINE', appearances, flush=True)
    assert len(requests) == 3, 'Observation replayed an old native input'
    assert view.contents.query(TranscriptHistory), 'Saved native source never mounted'
    assert 'NATIVE_AFTER_OLD_CHANNEL' in paint(app), 'Latest saved history never painted'
    assert not any(isinstance(child, AssignedIncomingMessage) and child.sequence == message.seq
                   for child in view.contents.children), 'Old checked inbound reappeared as a new live tail block'
    print('COLD_RETAINED_HISTORY_NO_LATE_OLD_TAIL_INPUT', flush=True)
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    observed.refresh_observation()
    await pilot.pause(2)
    assert len(requests) == 3
    assert not any(isinstance(child, AssignedIncomingMessage) and child.sequence == message.seq
                   for child in view.contents.children)
    print('ACTUAL_ACP_RECONNECT_NO_OLD_TAIL_INPUT', flush=True)
    # A fresh first input in the cold retained view must not resurrect old inputs.
    view.prompt.text = 'NEW_INPUT_IN_RETAINED_VIEW'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: len(requests) == 4 and not comms.registry.require('beta').executing)
    observed.refresh_observation()
    await pilot.pause(2)
    assert len(requests) == 4
    assert not any(isinstance(child, AssignedIncomingMessage) and child.sequence == message.seq
                   for child in view.contents.children)
    assert app._exception is None
    print('FIRST_NATIVE_INPUT_IN_COLD_RETAINED_VIEW_NO_OLD_REPLAY', flush=True)
    if os.environ.get('L0A_SWITCH_SOURCE'):
        await switching_inputs(app, pilot, comms, requests, message)



async def switching_inputs(app, pilot, comms, requests, old):
    from runtime_fixture import wait_channel_roster
    from toad.widgets.comms_sidebar import CommsRow
    from toad.widgets.session_tabs import SessionLabel
    from agent_comms.transcript_events import UserTranscript
    sidebar = await wait_channel_roster(app, pilot, '#team')
    beta_screen = app.selected_session
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == 'alpha')
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row)
    await until(pilot, lambda: app.selected_session is not beta_screen)
    await app.selected_session.wait_content_ready()
    alpha_screen = app.selected_session
    await until(pilot, lambda: alpha_screen.conversation.agent_ready, 40)
    screens = (beta_screen, alpha_screen, beta_screen, alpha_screen, beta_screen)
    samples = []
    profile = cProfile.Profile()
    profile.enable()
    try:
        for index, screen in enumerate(screens, 5):
            label = next(label for label in app.screen.query(SessionLabel) if label.id == screen.id)
            label.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            started, cpu = time.monotonic(), time.process_time()
            assert await pilot.click(label, offset=(label.size.width // 2, 0))
            await until(pilot, lambda: app.selected_session is screen)
            selected = time.monotonic()
            view = screen.conversation
            view.prompt.text = f'IMMEDIATE_RETURN_INPUT_{index}'
            view.prompt.prompt_text_area.focus()
            await pilot.press('enter')
            await until(pilot, lambda: len(requests) == index, 30)
            reached_provider = time.monotonic()
            await until(pilot, lambda: not comms.registry.require(view.agent.session_id).executing, 30)
            await pilot.pause(.3)
            assert not any(isinstance(child, AssignedIncomingMessage) and child.sequence == old.seq
                           for child in view.contents.children)
            samples.append({'thread': view.agent.session_id,
                'select_ms': round(1000*(selected-started), 1),
                'enter_to_provider_ms': round(1000*(reached_provider-selected), 1),
                'ui_cpu_ms': round(1000*(time.process_time()-cpu), 1)})
            assert app._exception is None
    finally:
        profile.disable()
        evidence = Path(os.environ['L0A_EVIDENCE'])
        profile.dump_stats(str(evidence / 'switch-send.prof'))
        with (evidence / 'switch-send-profile.txt').open('w') as stream:
            pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(40)
    print('PHYSICAL_LARGE_RETAINED_A_B_A_IMMEDIATE_SEND_CPU', samples, flush=True)
    assert len(requests) == 9
    fresh = await send_channel(comms, 'FRESH_PASSIVE_RECEIPT_AFTER_SWITCHING')
    await until(pilot, lambda: any(receipt.message and receipt.message.seq == fresh.seq
                and 'no response' in receipt.state.lower()
                for receipt in comms.views.recent_notifications('beta')), 30)
    view = beta_screen.conversation
    await until(pilot, lambda: bool(matching(view, fresh.seq)))
    assert len(matching(view, fresh.seq)) == 1
    original = matching(view, fresh.seq)[0]
    for _ in range(3):
        view.query_one(ObservedThreadActivity).refresh_observation()
        await pilot.pause(.3)
        assert len(matching(view, fresh.seq)) == 1
        assert 'no response' in str(matching(view, fresh.seq)[0].query_one('.assignment-handling').render()).lower()
    # Return through the real native retained source, not a notice suppression cache.
    page = comms.transcripts.thread_transcript_page('beta')
    assert sum(isinstance(event, UserTranscript) and event.routed
               and any(message.seq == fresh.seq for message in event.routing.requests)
               for event in page.events) == 1
    assert len(requests) == 11, requests
    print('FRESH_RECEIPT_ONCE_AND_HANDLING_UPDATES_NO_OLD_REPLAY', flush=True)


def reply(request, number):
    if 'bounded triage' in str(request):
        text = '{"decision":"IGNORE"}'
    else:
        text = ('NATIVE_AFTER_OLD_CHANNEL' if number == 3 else f'NATIVE_RESPONSE_{number}')
    return {'role': 'assistant', 'content': text}, 'stop'


if __name__ == '__main__':
    asyncio.run(main(prepare_state=prepare, acceptance=acceptance, provider_reply=reply,
                     provider_request_budget=11 if os.environ.get('L0A_SWITCH_SOURCE') else 4))
