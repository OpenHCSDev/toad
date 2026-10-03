"""Post-compaction zero usage is unknown, not an empty model context."""

import asyncio
import os
import tempfile
from importlib.resources import files
from pathlib import Path

from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.widgets.prompt import StatusLine
from agent_comms.comms import Comms
from agent_comms.acp_extension import ContextUsage, encode_updates
from comms_boundary_fixture import coordination_fact


async def main():
    ToadApp.CSS_PATH = files('toad').joinpath('toad.tcss')
    with tempfile.TemporaryDirectory(prefix="toad-context-usage-", dir='.artifacts') as directory:
        root = Path(directory).resolve()
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        Comms(root/'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            agent = Agent(root, AgentDefinition.decode({"name": "Fixture", "identity": "fixture",
                                 "short_name": "fixture", "run_command": {"*": "true"},
                                 "protocol": "acp"}), "fixture")
            view.agent=agent
            async def notify(update):
                result=await agent.server.call({'jsonrpc':'2.0','id':'context',
                    'method':'session/update','params':{'sessionId':'fixture','update':update}})
                assert 'error' not in result, result
                await pilot.pause()
            await notify({"sessionUpdate": "usage_update", "used": 120000,
                                                 "size": 272000, 'cost':{'amount':.5,'currency':'USD'}})
            await pilot.pause()
            assert "120.0K" in str(view.status)
            label=view.prompt.query_one(StatusLine)
            assert label.status.plain == view.status.plain == label.tooltip.plain
            frame='\n'.join(strip.text for strip in app.screen._compositor.render_strips())
            assert '120.0K' in frame and '44.1%' in frame
            await notify({"sessionUpdate": "usage_update", "used": 0,
                                                 "size": 272000})
            assert not agent.context_measurement.available
            assert "Context unavailable" in str(view.status)
            assert "0.0K" not in str(view.status)
            await notify({"sessionUpdate": "usage_update", "used": 27000,
                                                 "size": 272000})
            assert "27.0K" in str(view.status)
            saved=coordination_fact('fixture',root/'wire',worktree=str(root),
                                     context_usage=ContextUsage(38723,272000))
            await notify({'sessionUpdate':'agent_message_chunk', 'content':{'type':'text','text':''},
                          '_meta':encode_updates(saved)})
            assert 'last response' in view.status.plain and '38.7K' in view.status.plain
            agent.detach_surface(view)
            await notify({'sessionUpdate':'usage_update','used':40000,'size':272000})
            assert agent.context_measurement.used==40000
            view.bind_agent(agent)
            view.refresh_native_projection()
            await pilot.pause()
            frame='\n'.join(strip.text for strip in app.screen._compositor.render_strips())
            assert '40.0K' in frame and 'last response' not in view.status.plain
            app.save_screenshot(str(Path(os.environ['CONTEXT_EVIDENCE'])/'status.svg'))
            await agent.stop()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("context usage: unknown zero after compaction; next valid estimate restores percentage")


if __name__ == "__main__":
    asyncio.run(main())
