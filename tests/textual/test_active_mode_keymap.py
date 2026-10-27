"""Application remaps follow the live editor mode and shared sidebar focus."""

from textual.document._editing import VimInsert, VimNormal, VimVisual
from textual.widgets import Input

from toad.application_actions import CommanderAction
from toad.key_modes import VimNormal as NormalProfile
from toad.preferences import SETTINGS
from toad.screens.commander import CommanderPage
from toad.widgets.side_bar import SideBar


async def test_commander_remaps_follow_editor_transitions_and_sidebar_focus(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        app.saved_settings.set(SETTINGS.ui.key_mode, NormalProfile)
        editor = ui.conversation.prompt.prompt_text_area
        app.set_keymap({
            CommanderAction.binding_id(VimNormal): "f3",
            CommanderAction.binding_id(VimInsert): "f4",
            CommanderAction.binding_id(VimVisual): "f5",
        })
        for mode, key, other in ((VimNormal(), "f3", "f4"),
                                 (VimInsert(), "f4", "f3"),
                                 (VimVisual(), "f5", "f3")):
            editor.editing_mode = mode
            editor.focus()
            await ui.press(other)
            assert app.screen is app.workspace_screen
            await ui.press(key)
            await ui.until(lambda: isinstance(app.screen, CommanderPage),
                           why="the commander key for the editor's active mode")
            await ui.press("escape")
            await ui.until(lambda: app.screen is app.workspace_screen,
                           why="return from the commander page")
        sidebar = app.workspace_chrome.channels
        sidebar.reveal()
        assert isinstance(sidebar, SideBar)
        sidebar.query_one(Input).focus()
        await ui.press("f3")
        await ui.until(lambda: isinstance(app.screen, CommanderPage),
                       why="the application binding from shared sidebar focus")
