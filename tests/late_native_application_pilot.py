"""Original queued ACP effect versus actual saved-source publication.

Actual app, SDK validation, Agent, native message pump and compositor; an unstarted
Agent binds a private canonical source. No provider, ACP subprocess or input.
"""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from agent_comms.acp_extension import CoordinationChangedUpdate, TurnChangedUpdate, TranscriptSnapshotUpdate, encode_updates
from agent_comms.comms import Comms
from agent_comms.threads import Thread
from agent_comms.turn_lease import ActiveTurn, TurnState
from agent_comms.turn_phase import PublishingPhase
from toad.acp.agent import Agent
from toad.acp.agent_controller import AttachedSurfaceBinding
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.transcript_publication import CheckpointPublication
from toad.widgets.agent_response import AgentResponse
from toad.core.events import Update, CommsUpdated
from toad.widgets.transcript_history import TranscriptHistory

TOKEN = 'ORIGINAL_LATE_NATIVE_RESPONSE'

async def main():
    artifacts = Path(os.environ['LATE_NATIVE_ARTIFACTS']).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    held, release = asyncio.Event(), asyncio.Event()
    pending = []
    try:
        with TemporaryDirectory(dir=artifacts) as directory:
            root = Path(directory)
            os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'),
                              XDG_CONFIG_HOME=str(root/'config'),
                              XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'))
            comms = Comms(root/'wire'); comms.messaging.initialize_private_initial_protocol()
            thread = comms.registry.declare(Thread('source', frozenset(), str(root)))
            comms.registry.declare(Thread('peer', frozenset(), str(root)))
            comms.messaging.send_message('peer', 'source', 'ORIGINAL_WIRE_NOTICE')
            old_page = comms.transcripts.thread_transcript_page('source')
            app = ToadApp(project_dir=str(root))
            frames = []
            display = app._display
            def observe(screen, renderable):
                display(screen, renderable)
                if renderable is None or screen is not app.screen:
                    return
                view = app.selected_session.conversation
                visible = screen._compositor.visible_widgets
                blocks = [item for item in view.contents.query(AgentResponse) if item.source == TOKEN]
                if blocks:
                    frames.append({'ns': time.monotonic_ns(),
                        'resources': [{'id': id(item), 'visible': item in visible,
                                       'parent': type(item.parent).__name__} for item in blocks],
                        'busy': view.turns.owner.busy})
            app._display = observe
            async with app.run_test(size=(120, 35)) as pilot:
                try:
                    await app.selected_session.wait_content_ready()
                    view = app.selected_session.conversation
                    await view.transcript.suspend()
                    original_dispatch = view._dispatch_message
                    async def hold_original(message):
                        if isinstance(message, Update) and message.text == TOKEN:
                            held.set()
                            await release.wait()
                        await original_dispatch(message)
                    view._dispatch_message = hold_original
                    agent = Agent(root, AgentDefinition('custody','custody',{}), 'late-native')
                    view.set_reactive(type(view).agent, agent)
                    agent.controller.surface = AttachedSurfaceBinding(view, agent.events)
                    agent.coordination = CoordinationChangedUpdate(thread.incarnation, str(root/'wire'),
                        os.getpid(), str(root), None, None, thread.name, None)
                    binding = agent.presentation.managed_turns()
                    binding.receive(TurnState(ActiveTurn('original-turn', os.getpid(), phase=PublishingPhase())))
                    view.set_reactive(type(view).agent_ready, False)
                    history = TranscriptHistory(old_page)
                    await view.contents.mount(history)
                    await pilot.pause()
                    view.set_reactive(type(view).agent_ready, True)
                    history.loader = agent.get_transcript_page
                    view.window.anchor(); view.prompt.focus()
                    response = asyncio.create_task(agent.updates.receive('late-native',
                        {'sessionUpdate': 'agent_message_chunk', 'content': {'type':'text','text':TOKEN}}))
                    pending.append(response)
                    await asyncio.wait_for(held.wait(), 5)
                    # The native file and ordered completion become available while
                    # the original Conversation message has not applied its body.
                    source = root/'first-native.jsonl'
                    source.write_text(json.dumps({'type':'message','id':'original-assistant',
                        'message':{'role':'assistant','content':[{'type':'text','text':TOKEN}]}})+'\n')
                    comms.registry.declare(replace(thread, session_file=str(source)))
                    finished = asyncio.create_task(agent.updates.receive('late-native',
                        {'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':''},
                         '_meta': encode_updates(TurnChangedUpdate(TurnState(finished_turn_id='original-turn')))}))
                    pending.append(finished)
                    # Let original ingress/worker tasks run; don't ask Pilot to join
                    # the deliberately held Conversation's message pump.
                    await asyncio.sleep(.05)
                    view.transcript.dirty = view.transcript.checkpoint_required = True
                    case = os.environ.get('LATE_NATIVE_CASE', 'checkpoint')
                    if case == 'snapshot':
                        page = await agent.get_transcript_page()
                        publication = asyncio.create_task(view.transcript.snapshot(page))
                    elif case == 'queued_snapshot':
                        page = await agent.get_transcript_page()
                        agent.events.publish(CommsUpdated(TranscriptSnapshotUpdate.capture(comms.transcripts, 'source'), agent.session_id))
                        async def accepted_source():
                            async with asyncio.timeout(8):
                                while not any(item.committed_cursor == page.after
                                              for item in view.transcript.histories):
                                    await asyncio.sleep(.02)
                        publication = asyncio.create_task(accepted_source())
                    else:
                        publication = asyncio.create_task(view.transcript.publish(CheckpointPublication))
                    pending.append(publication)
                    await asyncio.sleep(.5)
                    before = {'response_receive_done':response.done(), 'finished_receive_done':finished.done(),
                              'source_publish_done':publication.done(),
                              'saved_resources':sum(item.source==TOKEN for item in view.contents.query(AgentResponse)),
                              'managed_busy':binding.owner.busy}
                    release.set()
                    await asyncio.wait_for(asyncio.gather(*pending), 8)
                    await pilot.pause(.5)
                    blocks = [item for item in view.contents.query(AgentResponse) if item.source==TOKEN]
                    receipt = {'case':case,'held':before,'final_resource_count':len(blocks),
                        'final_resources':[{'id':id(item),'parent':type(item.parent).__name__} for item in blocks],
                        'duplicate_frames':sum(sum(item['visible'] for item in frame['resources'])>1 for frame in frames),
                        'frames':len(frames), 'native_started':agent.process.runner is not None,
                        'registered_histories':len(view.window.histories)}
                    (artifacts/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
                    (artifacts/'admitted-frames.json').write_text(json.dumps(frames,indent=2)+'\n')
                    print(json.dumps(receipt),flush=True)
                    assert not receipt['native_started']
                    assert len(blocks)==1 and not receipt['duplicate_frames'], receipt
                finally:
                    release.set()
                    for task in pending:
                        if not task.done(): task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
            assert app._exception is None
    finally:
        release.set()
        for task in pending:
            if not task.done(): task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)

if __name__=='__main__': asyncio.run(main())
