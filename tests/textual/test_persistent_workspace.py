"""Textual-facing: one workspace screen and tab strip persist across sessions, and each session keeps its own editor document and undo history."""

from toad.screens.workspace import WorkspaceScreen
from toad.widgets.session_tabs import SessionsTabs


async def test_sessions_keep_their_editor_state_inside_one_workspace_screen(workspace):
    workspace.thread(workspace.project.name)
    async with workspace.app(size=(130, 44)) as ui:
        app, _ = ui.textual
        first = app.selected_session
        assert first is not None
        screen = app.screen
        assert isinstance(screen, WorkspaceScreen)
        editor = first.conversation.prompt.prompt_text_area
        editor.insert("persistent draft")
        editor.history.checkpoint()
        editor.insert(" with undo")
        document, history = editor.document, editor.history
        header = screen.query_one(SessionsTabs)
        second = await ui.new_session()
        assert app.screen is screen
        assert app.selected_session is not first
        await ui.write_draft("second draft")
        await ui.select_tab(first.id)
        restored = app.selected_session.conversation.prompt.prompt_text_area
        assert restored.document is document and restored.history is history
        restored.undo()
        assert restored.text == "persistent draft"
        assert app.screen is screen and screen.query_one(SessionsTabs) is header
        await ui.select_tab(second)
        assert ui.draft() == "second draft"
        await ui.close_tab(second)
        assert app.selected_session is first
        assert second not in [tab.identity for tab in ui.tabs()]
        assert second not in app.workspace_sessions.views
        assert first.conversation.prompt.prompt_text_area is editor
        assert editor.text == "persistent draft"
