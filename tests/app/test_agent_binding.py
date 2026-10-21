"""Each launch binding keeps matching with its existing native view."""

from support.agents import peer

from toad.screens.main import MainScreen
from toad.session_scope import AgentSession
from toad.thread_identity import NoThreadIdentity


async def test_no_agent_does_not_match_a_launch(workspace):
    view = MainScreen(workspace.project)
    assert not view.matches_launch("not-bound", "not-bound")
    assert view.thread_identity == NoThreadIdentity()


async def test_attached_agent_matches_its_live_session_and_relaunch_reuses_the_view(
    workspace,
):
    definition = peer("echo")
    async with workspace.app(agent=definition) as ui:
        app, _ = ui.textual
        await ui.until_agent_ready()
        original = app.selected_session
        mode = ui.selected_tab
        session_id = ui.conversation.agent_binding.session_id
        assert original.matches_launch(definition.identity, session_id)
        assert not original.matches_launch(definition.identity + "-other", session_id)
        await app.session_navigation.launch(
            definition.identity, agent_session_id=session_id
        )
        assert ui.selected_tab == mode
        assert app.selected_session is original
        await ui.write_draft("binding relaunch journey")
        await ui.press("enter")
        await ui.until_shows("PEER_ANSWER binding relaunch journey")


async def test_agent_session_matches_its_saved_session_without_crossing_agent_identity(
    workspace,
):
    definition = peer("echo")
    view = MainScreen(workspace.project, AgentSession(definition, "retained-session"))
    assert view.matches_launch(definition.identity, "retained-session")
    assert not view.matches_launch(definition.identity + "-other", "retained-session")
    assert view.thread_identity.thread_name() == "retained-session"
