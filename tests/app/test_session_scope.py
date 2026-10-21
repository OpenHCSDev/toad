"""Session consumers discover the existing mounted owner without a screen cycle."""
import sys

from toad.session_scope import SessionScope
from support.agents import peer


async def test_scope_import_and_real_conversation_ancestor(workspace):
    assert "toad.screens.session_view" not in sys.modules
    async with workspace.app(agent=peer("echo")) as ui:
        app, _pilot = ui.textual
        first = ui.selected_tab
        view = app.selected_session
        assert ui.conversation.query_ancestor(SessionScope) is view
        await ui.until_agent_ready()
        await ui.write_draft("session scope journey")
        await ui.press("enter")
        await ui.until_shows("PEER_ANSWER session scope journey")
        second = await ui.new_session()
        assert second != first
        assert ui.conversation.query_ancestor(SessionScope) is app.selected_session
        await ui.select_tab(first)
        assert app.selected_session is view
        assert ui.conversation.query_ancestor(SessionScope) is view
        await ui.until_shows("PEER_ANSWER session scope journey")
