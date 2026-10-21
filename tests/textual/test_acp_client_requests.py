"""Textual-facing: a scripted ACP agent uses every client request (modes, files, permission, terminals);
the permission dialog and the tool call block are the Textual widgets that answer and show them."""
from toad.session_scope import AgentAttached

from support.agents import peer
from toad.core import input_events
from toad.screens.permissions import PermissionsScreen
from toad.widgets.tool_call import ToolCall


async def test_agent_requests_are_served_and_the_reply_is_drawn(workspace):
    async with workspace.app(size=(130, 44), binding=AgentAttached(peer("specification"))) as ui:
        app, _pilot = ui.textual
        await ui.until_agent_ready()
        view = ui.conversation
        agent = view.agent_binding
        try:
            await ui.until(lambda: agent.current_mode is not None, why="the advertised modes")
            assert agent.current_mode is agent.available_modes[0]
            assert await agent.set_mode("write") is None
            await ui.until(lambda: agent.current_mode is agent.available_modes[1], why="the mode change")
            await view.submit_input(input_events.UserInputSubmitted("SDK_SPECIFICATION_JOURNEY"))
            await ui.until(lambda: isinstance(app.screen, PermissionsScreen), why="the permission dialog")
            await ui.until(lambda: ui.shows("old SDK content") and ui.shows("new SDK content"), why="the proposed edit")
            assert ui.shows("Allow SDK edit")
            await ui.press("a")
            await ui.until(lambda: (workspace.project / "rpc-results.json").exists(), seconds=30,
                           why="the agent to finish its requests")
            await ui.until_shows("SDK_RPC_JOURNEY_COMPLETE")
            assert view.query_one(ToolCall).tool_call.completed
            assert (workspace.project / "sdk-file.txt").read_text() == "new SDK content"
            workspace.release("painted")
            await ui.until_agent_ready()
            assert not agent.permissions.pending
        finally:
            workspace.release("painted")
            await agent.stop()
