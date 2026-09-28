"""Fresh producer process -> ACP JSON -> actual mounted Toad consumer."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

PRODUCER = '''
import asyncio,json
from agent_comms.transcript_updates import StartedTranscriptUpdate
from agent_comms.agent_event_updates import AcpEventConsumer
from agent_comms import agent_events
class Pipe:
    async def session_update(self,session_id,update):
        print(json.dumps({"jsonrpc":"2.0","method":"session/update","params":{
            "sessionId":session_id,"update":update.model_dump(by_alias=True,exclude_none=True)}}),flush=True)
async def main():
    pipe=Pipe()
    await StartedTranscriptUpdate(turn_id="actual-producer",started_at=1.0).publish("pilot",pipe)
    consumer=AcpEventConsumer(None,"pilot",pipe)
    await consumer.on_compaction(agent_events.CompactionStart())
    await consumer.on_compaction(agent_events.CompactionProgress(1, 50, 100))
    await consumer.on_compaction(agent_events.CompactionEnd(summary="Native event summary"))
    await consumer.settled("stale-turn")
    await consumer.settled("actual-producer")
asyncio.run(main())
'''

async def main():
    from runtime_fixture import ToadApp
    from toad.acp.agent import Agent
    with tempfile.TemporaryDirectory(prefix="t2-paired-",dir=Path(__file__).parents[2]) as directory:
        root=Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'),
                          XDG_STATE_HOME=str(root/'state'),AGENT_COMMS_ROOT=str(root/'wire'))
        child=await asyncio.create_subprocess_exec(sys.executable,'-c',PRODUCER,stdout=asyncio.subprocess.PIPE)
        raw=(await child.stdout.read()).splitlines()
        assert await child.wait()==0
        app=ToadApp(project_dir=str(root))
        async with app.run_test(size=(90,30)) as pilot:
            await pilot.pause()
            view=app.screen.conversation
            agent=Agent(root,{'name':'T2','identity':'t2','short_name':'t2','run_command':{'*':'true'},'protocol':'acp'},'pilot')
            view.agent=agent
            agent._message_target=view
            await agent.server.call(json.loads(raw[0]))
            await pilot.pause()
            assert agent._active_turn_id=='actual-producer'
            assert view._managed_turn_id=='actual-producer'
            assert view.busy_count==1
            await agent.server.call(json.loads(raw[1]))
            await pilot.pause()
            assert view.activity == "Compacting context…"
            await agent.server.call(json.loads(raw[2]))
            await pilot.pause()
            assert "50% of input processed" in view.activity
            await agent.server.call(json.loads(raw[3]))
            await pilot.pause()
            assert "50% of input processed" not in view.activity
            await agent.server.call(json.loads(raw[4]))
            await pilot.pause()
            assert view._managed_turn_id=="actual-producer"
            await agent.server.call(json.loads(raw[5]))
            await pilot.pause()
            assert agent._active_turn_id is None
            assert view._managed_turn_id is None
            assert view.busy_count==0
            assert app._exception is None
    print('Fresh producer ACP notifications reached mounted Toad turn and compaction states; stale settle rejected; no provider call')

if __name__ == '__main__':
    asyncio.run(main())
