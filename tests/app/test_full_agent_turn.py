"""One turn of every kind of agent output reaches the conversation: the same turn the Qt
drive (``tools/qt_drive.py agent_session``) sends its view, so the two frontends compare."""
from toad.launch_binding import AgentAttached

from support.agents import FULL_TURN, peer, script


async def test_a_full_turn_streams_asks_and_runs_its_terminal(workspace):
    async with workspace.app(size=(120, 50), binding=AgentAttached(peer("scripted"))) as ui:
        await ui.until_agent_ready()
        await ui.write_draft(script(*FULL_TURN))
        await ui.press("enter")
        await ui.until_shows("TURN_REPLY one two three")
        await ui.until_shows("TURN_TOOL read")
        await ui.until_shows("TURN_PERMISSION")
        await ui.until_shows("a Allow")
        await ui.press("a")
        await ui.until_shows("TURN_DONE", seconds=20)
        assert ui.shows("TURN_TERMINAL_OUTPUT")
        facts = workspace.received()
        assert [fact["answered"] for fact in facts if "answered" in fact] == ["Allow"]
        assert [fact["terminal_exit"] for fact in facts if "terminal_exit" in fact] == [0]
