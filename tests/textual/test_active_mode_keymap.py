"""Application remaps work from shared sidebar focus and the Close button."""

from textual.widgets import Input

from toad.application_actions import CommanderAction
from toad.key_modes import VimNormal
from toad.preferences import SETTINGS
from toad.screens.commander import CommanderPage
from toad.widgets.side_bar import SideBar
from toad.widget_actions import DismissAction


async def test_commander_remaps_from_sidebar_and_close_button(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        app.saved_settings.set(SETTINGS.ui.key_mode, VimNormal)
        remaps = {CommanderAction.binding_id(VimNormal): "f3"}
        app.set_keymap(remaps)
        sidebar = app.workspace_chrome.channels
        sidebar.reveal()
        assert isinstance(sidebar, SideBar)
        sidebar.query_one(Input).focus()
        await ui.press("f3")
        await ui.until(lambda: isinstance(app.screen, CommanderPage),
                       why="the application binding from shared sidebar focus")
        app.set_keymap({**remaps, DismissAction.binding_id(VimNormal): "f6"})
        await ui.press("escape")
        assert isinstance(app.screen, CommanderPage)
        await ui.press("f6")
        await ui.until(lambda: app.screen is app.workspace_screen,
                       why="the remapped modal dismissal")
        await ui.press("f3")
        await ui.until(lambda: isinstance(app.screen, CommanderPage),
                       why="the commander page reopened under the remap")
        await ui.pilot.click("#commander-close")
        await ui.until(lambda: app.screen is app.workspace_screen,
                       why="the Close button uses the same dismissal action")
