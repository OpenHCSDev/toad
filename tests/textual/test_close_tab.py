"""Textual-facing: closing a tab with a long mounted history drops it from the strip before its widgets are torn down, and the closing view is not drawn up again on the way out."""

from unittest.mock import patch

from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation
from toad.widgets.prompt import Prompt


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


async def test_closing_a_tab_releases_its_agent_without_titling_or_configuring_the_closing_view(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        identity = await ui.new_session()
        conversation = ui.conversation
        # A bound agent, as an open native tab has: releasing it must not become another update of the view.
        ui.attach_agent(ui.detached_agent())
        await ui.step()
        prompt = conversation.prompt
        updated = []
        sync_configuration, sync_project = Prompt.sync_configuration, Conversation.sync_project_path

        def configured(view, *args, **kwargs):
            if view is prompt:
                updated.append("prompt configuration")
            return sync_configuration(view, *args, **kwargs)

        def synced(view, *args, **kwargs):
            if view is conversation:
                updated.append("project sync")
            return sync_project(view, *args, **kwargs)

        with (patch.object(Conversation, "sync_project_path", synced),
              patch.object(Prompt, "sync_configuration", configured)):
            await ui.close_tab(identity)
        assert not updated, ("The closing view was updated again", updated)
        assert conversation.agent is None and not conversation.is_attached
