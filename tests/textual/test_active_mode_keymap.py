"""Application remaps work from shared sidebar focus and the Close button."""

import pytest
from textual.widgets import Input

from toad.application_actions import CommanderAction
from toad.key_modes import KeyMode, Standard, VimNormal
from toad.neovim_editing import NeovimEditing
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


@pytest.mark.parametrize("mode", KeyMode.members_with(NeovimEditing))
async def test_application_binding_precedes_real_engine_in_each_profile(workspace, mode):
    async with workspace.app(size=(120, 40)) as ui:
        app = ui.app
        area = ui.conversation.prompt.prompt_text_area
        app.saved_settings.set(SETTINGS.ui.key_mode, Standard)
        await ui.until(lambda: area.key_mode is Standard, why="the native draft editor")
        area.focus()
        await ui.type("keep draft")
        app.saved_settings.set(SETTINGS.ui.key_mode, mode)
        await ui.until(lambda: area.key_mode is mode, why="the declared engine profile")
        await ui.until(lambda: area.editing_mode.completed,
                       why="the real native mode before the application shortcut")
        await ui.press("f2")
        await ui.until(lambda: isinstance(app.screen, CommanderPage),
                       why="the default commander key before engine forwarding")
        await ui.pilot.click("#commander-close")
        await ui.until(lambda: app.screen is app.workspace_screen, why="the original prompt again")
        area.focus()
        assert area.text == "keep draft"
        app.set_keymap({CommanderAction.binding_id(mode): "f3"})
        await ui.press("f3")
        await ui.until(lambda: isinstance(app.screen, CommanderPage),
                       why="the configured application key through the same binding owner")
        await ui.pilot.click("#commander-close")
        await ui.until(lambda: app.screen is app.workspace_screen, why="the retained prompt")
        assert area.text == "keep draft"
