"""An agent that cannot start is reported in the conversation and never accepts input."""
from toad.session_scope import AgentAttached

import sys

from support.agents import command, peer


async def test_a_process_that_exits_during_startup_is_reported(workspace):
    agent = command(sys.executable, "-c", "import sys; sys.stdin.readline()  # exits_during_startup")
    async with workspace.app(size=(139, 25), binding=AgentAttached(agent)) as ui:
        await ui.until_shows("ACP process closed", seconds=20)
        assert not ui.agent_ready()
        await ui.until(lambda: not workspace.child_processes("exits_during_startup"), why="the agent process to be gone")


async def test_a_refused_handshake_is_reported_as_not_sent(workspace):
    # The refusing process stays attached: a later owner may accept the same connection.
    async with workspace.app(size=(139, 25), binding=AgentAttached(peer("refuses_initialize"))) as ui:
        await ui.until_shows("AGENT_REFUSED_TO_START", seconds=20)
        assert ui.shows("Not sent")
        assert not ui.agent_ready()
