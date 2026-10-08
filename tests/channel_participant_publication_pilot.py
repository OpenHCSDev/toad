"""Real private channel updates borrow captured participant paint off the UI task."""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
from threading import get_ident
from time import perf_counter

from textual.content import Content

from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import Comms
from agent_comms.presentation import ThreadView
from agent_comms.thread_execution import ExternalThreadExecution
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.comms_chat import CommsChatView


async def until(predicate):
    async with asyncio.timeout(20):
        while not predicate():
            await asyncio.sleep(.01)


async def main(output: Path):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    project = output / 'project'
    project.mkdir()
    for key in tuple(os.environ):
        if key.startswith('AGENT_COMMS_'):
            os.environ.pop(key)
    os.environ.update(AGENT_COMMS_ROOT=str(output / 'wire'),
                      XDG_CONFIG_HOME=str(output / 'config'),
                      XDG_STATE_HOME=str(output / 'state'),
                      XDG_DATA_HOME=str(output / 'data'),
                      TOAD_TEST_ATTEMPT=str(output))
    service = Comms(output / 'wire', private_initial_writes=True)
    service.messaging.initialize_private_initial_protocol()
    leases = []
    for index in range(24):
        owner = service.registry.declare(Thread(
            f'participant-{index:02}', frozenset({'team'}), str(project),
            process_identity=ProcessIdentity.capture(os.getpid()),
            execution=ExternalThreadExecution,
        ))
        leased, _ = service.registry.lease_local_turn(owner.name, f'private-turn-{index}')
        leases.append(leased.require_turn_lease())
    app = ToadApp(project_dir=str(project))
    loop_thread = get_ident()
    calls = Counter()
    monitor = sys.monitoring
    monitor_id = monitor.PROFILER_ID
    codes = {ThreadView.presentation.fget.__code__: 'presentation',
             ChannelParticipants.prepare_participants.__code__: 'participant_paint'}
    monitor.use_tool_id(monitor_id, 'channel-participant-publication')
    monitor.register_callback(monitor_id, monitor.events.PY_START,
                              lambda code, offset: calls.update(
                                  (f'{codes[code]}:{"UI" if get_ident() == loop_thread else "worker"}',)))
    for code in codes:
        monitor.set_local_events(monitor_id, code, monitor.events.PY_START)
    gaps = []
    running = True
    async def sample():
        previous = perf_counter()
        while running:
            await asyncio.sleep(.005)
            now = perf_counter()
            gaps.append(1000 * (now - previous))
            previous = now
    sampler = asyncio.create_task(sample())
    try:
        async with app.run_test(size=(110,38)) as pilot:
            await app.selected_session.wait_content_ready()
            await channel_target('#team').open(NavigationContext(
                app, app.selected_mode, project, 'participant-00'))
            chat = app.screen.query_one(CommsChatView)
            participants = chat.query_one(ChannelParticipants)
            await until(lambda: isinstance(participants.names.content, Content)
                        and 'participant-23' in participants.names.content.plain)
            assert all(f'participant-{index:02}' in participants.names.content.plain
                       for index in range(24))
            prompt = chat.query_one(ChannelPrompt)
            prompt.text = 'Retained draft'
            prompt.focus()
            receipt = await asyncio.to_thread(service.messaging.send_initial_cohort,
                'participant-00', '#team', 'Original private channel update for all recipients')
            await until(lambda: any(message.message_id == receipt.message_id
                                   for message, _ in chat.message_history.rows))
            await pilot.press('x')
            assert prompt.text.endswith('x') and 'Retained draft' in prompt.text
            async def release_all():
                for lease in leases:
                    await asyncio.to_thread(service.registry.release_turn, lease)
            await release_all()
            leases.clear()
            await until(lambda: participants.names.content.plain == 'No active turns')
            assert len(prompt._candidates) == 24  # Idle members remain mentionable.
            assert calls['participant_paint:worker'] > 0
            assert calls['participant_paint:UI'] == 0
            assert app._exception is None
        result = {'recipients':24, 'committed_messages':1, 'paint_calls':dict(calls),
                  'participant_retirement_painted':True, 'mentions_retained':24,
                  'draft_preserved':True, 'max_loop_gap_ms':max(gaps),
                  'provider_inputs':0, 'claim':'Headless source App; not live provider or physical frame pacing'}
        (output/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result), flush=True)
    finally:
        for lease in leases:
            await asyncio.to_thread(service.registry.release_turn, lease)
        running = False
        await sampler
        for code in codes:
            monitor.set_local_events(monitor_id, code, 0)
        monitor.free_tool_id(monitor_id)


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1])))
