"""Textual-facing: closing a tab with a long mounted history drops it from the strip before its widgets are torn down, and the closing view is not drawn up again on the way out."""

from unittest.mock import patch

from toad.widgets.agent_response import AgentResponse


async def test_closed_tab_leaves_the_strip_before_its_view_is_removed(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        base = ui.selected_tab
        for _ in range(2):
            identity = await ui.new_session()
            await ui.conversation.contents.mount(*[
                AgentResponse(f"Response {i}\n\n" + "long paragraphs.\n\n" * 10) for i in range(14)])
            await ui.step()
            visible_at_teardown = []
            teardown = app.workspace_sessions.close

            async def watched_close(closing):
                visible_at_teardown.append(identity in [tab.identity for tab in ui.tabs()])
                return await teardown(closing)

            with patch.object(app.workspace_sessions, "close", watched_close):
                await ui.close_tab(identity)
            assert visible_at_teardown == [False], "Closed tab remained visible during view teardown"
            assert ui.selected_tab == base and identity not in app.tab_order.names
