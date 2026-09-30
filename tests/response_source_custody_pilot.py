"""Actual source/live response transfer across an ordered managed settlement.

No ACP/native runner or provider starts; installed first-fork acceptance is separate.
"""
import asyncio,json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_comms.comms import Comms
from agent_comms.threads import Thread
from agent_comms.acp_extension import CoordinationChangedUpdate
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
from toad.transcript_publication import CheckpointPublication, SnapshotPublication

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
            assert wire['sent_resources']==wire['incoming_resources']==1,wire
            assert wire['wire_frontier']==incoming.seq and wire['native_transfer_pending'],wire
            print(json.dumps(wire))
            assert binding.receive(TurnState(finished_turn_id='source-turn'))
            await view.output.settle()
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
            responses=[widget for widget in view.contents.query(AgentResponse) if 'SOURCE_RESPONSE_ONCE' in widget.source]
            settled={'response_resources':len(responses),'live_response_attached':block.is_attached,'history_frontier_advanced':history.committed_cursor.offset>old_page.after.offset,'history_count':len(view.window.histories),'managed_busy':view.turns.owner.busy}
            print(json.dumps(settled))
            assert len(responses)==1 and not block.is_attached and settled['history_frontier_advanced'],settled
            # An active turn does not bar first paint or replacement of saved
            # resources when there is no anonymous live output to transfer.
            assert binding.receive(TurnState(ActiveTurn('next-turn',os.getpid(),phase=PublishingPhase())))
            source.write_text(source.read_text()+json.dumps({'type':'message','message':{'role':'assistant','content':'SAVED_FOLLOWUP'}})+'\n')
            page=await agent.get_transcript_page()
            # A same-source snapshot requests a checkpoint rather than a
            # second full history. Exercise initial saved admission separately
            # through actual retirement of this window's existing resource.
            await view.transcript.suspend()
            await history.remove()
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
            (folder/'receipt-fixed.json').write_text(json.dumps({'publishing':receipt,'independent_wire':wire,'settled':settled,'active_saved_source':active_saved},indent=2)+'\n')
            assert agent.process.process is None and agent.process.runner is None
if __name__ == '__main__':
    asyncio.run(main())
