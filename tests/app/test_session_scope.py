"""Session consumers discover the existing mounted owner without a screen cycle."""

import sys

import pytest
from agent_comms.errors import RelationViolationError
from agent_comms.launch_root import LaunchRoot
from support.agents import peer

from toad.session_scope import NoSessionOrigin, NoTranscript, SessionScope


async def test_scope_import_and_real_conversation_ancestor(workspace):
    assert "toad.screens.session_view" not in sys.modules
    unavailable = NoSessionOrigin("closed-test-view")
    assert unavailable.transcript_scope() == NoTranscript()
    with pytest.raises(RelationViolationError, match="closed-test-view"):
        unavailable.resolve_thread()
    LaunchRoot.from_path(workspace.roots.wire).install()
    definition = peer("echo")
    async with workspace.app(agent=definition) as ui:
        app, _pilot = ui.textual
        first = ui.selected_tab
        view = app.selected_session
        assert ui.conversation.query_ancestor(SessionScope) is view
        await ui.until_agent_ready()
        await ui.write_draft("session scope journey")
        await ui.press("enter")
        await ui.until_shows("PEER_ANSWER session scope journey")
        assert app.workspace_sessions.native_origins[first] is view
        assert view.matches_launch(
            definition.identity, ui.conversation.agent_binding.session_id
        )
        sidebar = app.workspace_chrome.channels
        if sidebar.collapsed:
            sidebar.toggle()
            await ui.step()
        sidebar.toggle()
        await ui.until(
            lambda: app.focused is ui.conversation.prompt.prompt_text_area,
            why="collapsing the sidebar returns input focus",
        )
        second = await ui.new_session()
        assert second != first
        assert ui.conversation.query_ancestor(SessionScope) is app.selected_session
        await ui.select_tab(first)
        assert app.selected_session is view
        assert ui.conversation.query_ancestor(SessionScope) is view
        await ui.until_shows("PEER_ANSWER session scope journey")
        await ui.close_tab(second)
        assert second not in app.workspace_sessions.native_origins
        with pytest.raises(RelationViolationError):
            app.workspace_sessions.origin(second).resolve_thread()
