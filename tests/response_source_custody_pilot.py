"""Actual source/live response transfer across an ordered managed settlement.

No ACP/native runner or provider starts; installed first-fork acceptance is separate.
"""
import asyncio,json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_comms.comms import Comms
from agent_comms.threads import Thread
from agent_comms.acp_extension import CoordinationChangedUpdate, TurnChangedUpdate
from toad.acp.messages import CommsUpdated
from agent_comms.turn_lease import ActiveTurn,TurnState
from agent_comms.turn_phase import PublishingPhase
from toad.app import ToadApp
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.live_output import ResponseStream
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.outgoing_message import OutgoingMessage
from toad.transcript_publication import CheckpointPublication, SnapshotPublication, ObservedSourcePublication

async def main():
    folder=Path(os.environ['RESPONSE_CUSTODY_ARTIFACTS']).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=folder) as directory:
        root=Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'),XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'))
        comms=Comms(root/'wire');comms.messaging.initialize_private_initial_protocol()
        source=root/'source.jsonl'
        source.write_text(json.dumps({'type':'message','message':{'role':'assistant','content':'SAVED_PARENT_RESPONSE'}})+'\n')
        comms.registry.declare(Thread('source',frozenset(),str(root),session_file=str(source)))
        comms.registry.declare(Thread('peer',frozenset(),str(root)))
        old_page=comms.transcripts.thread_transcript_page('source')
        source.write_text(source.read_text()+json.dumps({'type':'message','message':{'role':'assistant','content':'SOURCE_RESPONSE_ONCE'}})+'\n')
        app=ToadApp(project_dir=str(root))
        frames=[]
        display=app._display
        def observe_frame(screen, renderable):
            display(screen, renderable)
            if renderable is None or screen is not app.screen:
                return
            view=app.selected_session.conversation
            visible=screen._compositor.visible_widgets
            resources=[widget for widget in view.contents.query(AgentResponse)
                       if 'SOURCE_RESPONSE_ONCE' in widget.source and widget in visible]
            if resources:
                frames.append({'response_resources':len(resources),
                               'resource_ids':[id(widget) for widget in resources],
                               'native_mutating':view.window.history_mutating(),
                               'preparation_suspended':view.window.document_viewport._suspended})
        app._display=observe_frame
        async with app.run_test(size=(120,35)) as pilot:
            await app.selected_session.wait_content_ready()
            view=app.selected_session.conversation
            await view.transcript.suspend()
            agent=Agent(root,AgentDefinition('custody','custody',{}),None)
            view.set_reactive(type(view).agent,agent)
            thread=comms.registry.require('source')
            agent.coordination=CoordinationChangedUpdate(thread.incarnation,str(root/'wire'),os.getpid(),str(root),None,None,thread.name,None)
            view.set_reactive(type(view).agent_ready,False)
            binding=agent.presentation.managed_turns()
            binding.receive(TurnState(ActiveTurn('source-turn',os.getpid(),phase=PublishingPhase())))
            history=TranscriptHistory(old_page)
            await view.contents.mount(history);await pilot.pause()
            view.set_reactive(type(view).agent_ready,True)
            history.loader=agent.get_transcript_page
            block=await view.output.append(ResponseStream(turn_id='source-turn'),'SOURCE_RESPONSE_ONCE')
            await pilot.pause()
            sent=comms.messaging.send_message('source','peer','WIRE_SENT_DURING_ANONYMOUS_OUTPUT')
            incoming=comms.messaging.send_message('peer','source','WIRE_INCOMING_DURING_ANONYMOUS_OUTPUT')
            observed=ObservedSourcePublication(view.transcript,view,view.window,view.contents,
                                              await agent.get_thread_presentation())
            observed_page=await observed.read_page()
            observed_read={'native_prefix_retained':observed_page.after.offset==old_page.after.offset,
                           'assigned_frontier_advanced':observed_page.after.wire_seq==incoming.seq}
            assert all(observed_read.values()),observed_read
            print(json.dumps({'observed_read':observed_read,'events':[type(e).__name__ for e in observed_page.events]}))
            view.window.anchor();view.prompt.focus()
            view.transcript.dirty=view.transcript.checkpoint_required=True
            task=asyncio.create_task(CheckpointPublication(view.transcript,view,view.window,view.contents).publish())
            try:
                async with asyncio.timeout(8):
                    while not task.done():
                        await pilot.pause(.02)
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
            await pilot.pause()
            # An observed source read may already have admitted the original
            # coalesced checkpoint. A second operation can decline while that
            # source worker still owns native mounting. Join its actual rows,
            # not just completion of this caller's declined operation.
            async with asyncio.timeout(8):
                while not (any(w.message_reference.seq==sent.seq for w in view.contents.query(OutgoingMessage))
                           and any(w.message_reference.seq==incoming.seq for w in view.contents.query(IncomingMessage))):
                    await pilot.pause(.02)
            responses=[widget for widget in view.contents.query(AgentResponse) if 'SOURCE_RESPONSE_ONCE' in widget.source]
            receipt={'live_response_attached':block.is_attached,'response_resources':len(responses),'history_frontier_advanced':history.committed_cursor.offset>old_page.after.offset,'managed_phase':type(view.turns.owner.state.phase).__name__,'managed_busy':view.turns.owner.busy,'history_count':len(view.window.histories),'response_resource_ids':[id(widget) for widget in responses]}
            print(json.dumps(receipt))
            assert not receipt['history_frontier_advanced'], receipt
            assert len(responses)==1,receipt
            wire={'sent_resources':sum(w.message_reference.seq==sent.seq for w in view.contents.query(OutgoingMessage)),
                  'incoming_resources':sum(w.message_reference.seq==incoming.seq for w in view.contents.query(IncomingMessage)),
                  'wire_frontier':history.committed_cursor.wire_seq,
                  'native_frontier':history.committed_cursor.offset,
                  'live_response_attached':block.is_attached,
                  'native_transfer_pending':view.transcript.dirty}
            print(json.dumps({'wire':wire,'pages':[{'before':p.page.before.offset,'after':p.page.after.offset,'wire_before':p.page.before.wire_seq,'wire_after':p.page.after.wire_seq,'events':[type(e).__name__ for e in p.page.events],'start':p.start,'stop':p.stop,'children':len(p.children)} for p in history.pages],'state':type(history.state).__name__}))
            assert wire['sent_resources']==wire['incoming_resources']==1,wire
            assert wire['wire_frontier']==incoming.seq and wire['native_transfer_pending'],wire
            print(json.dumps(wire))
            assert binding.receive(TurnState(finished_turn_id='source-turn'))
            await view.on_turn_changed(CommsUpdated(TurnChangedUpdate(binding.owner.state),
                                       agent=agent,session_id=agent.session_id,sequence=binding.sequence))
            task=asyncio.create_task(CheckpointPublication(view.transcript,view,view.window,view.contents).publish())
            try:
                async with asyncio.timeout(8):
                    while not task.done():
                        await pilot.pause(.02)
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
            await pilot.pause()
            async with asyncio.timeout(8):
                while block.is_attached:
                    await pilot.pause(.02)
            responses=[widget for widget in view.contents.query(AgentResponse) if 'SOURCE_RESPONSE_ONCE' in widget.source]
            settled_history=next(iter(view.transcript.histories))
            settled={'response_resources':len(responses),'live_response_attached':block.is_attached,'history_frontier_advanced':settled_history.committed_cursor.offset>old_page.after.offset,'history_count':len(view.window.histories),'managed_busy':view.turns.owner.busy,
                     'captured_history_retired':not history.is_attached,
                     'accepted_history_registered':settled_history in view.window.histories}
            print(json.dumps(settled))
            assert len(responses)==1 and not block.is_attached and settled['history_frontier_advanced'],settled
            (folder/'admitted-frames.json').write_text(json.dumps(frames,indent=2)+'\n')
            assert frames and all(frame['response_resources']==1 for frame in frames),frames
            # An active turn does not bar first paint or replacement of saved
            # resources when there is no anonymous live output to transfer.
            assert binding.receive(TurnState(ActiveTurn('next-turn',os.getpid(),phase=PublishingPhase())))
            source.write_text(source.read_text()+json.dumps({'type':'message','message':{'role':'assistant','content':'SAVED_FOLLOWUP'}})+'\n')
            page=await agent.get_transcript_page()
            # A same-source snapshot requests a checkpoint rather than a
            # second full history. Exercise initial saved admission separately
            # through actual retirement of this window's existing resource.
            await view.transcript.suspend()
            await settled_history.remove()
            snapshot=SnapshotPublication(view.transcript,view,view.window,view.contents,page)
            assert snapshot.current() and snapshot.source_current(page.after)
            task=asyncio.create_task(snapshot.publish())
            try:
                async with asyncio.timeout(8):
                    while not task.done():
                        await pilot.pause(.02)
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
            await pilot.pause()
            active_saved={'history_count':len(view.window.histories),'old_history_attached':history.is_attached,'managed_busy':view.turns.owner.busy,'frontier_matches':next(iter(view.window.histories)).committed_cursor==page.after}
            assert active_saved['history_count']==1 and not history.is_attached and active_saved['frontier_matches'],active_saved
            print(json.dumps(active_saved))
            (folder/'receipt-fixed.json').write_text(json.dumps({'observed_read':observed_read,'publishing':receipt,'independent_wire':wire,'settled':settled,'active_saved_source':active_saved},indent=2)+'\n')
            assert agent.process.process is None and agent.process.runner is None
if __name__ == '__main__':
    asyncio.run(main())
