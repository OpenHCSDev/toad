"""The menu edits saved mode-specific bindings, including its own opening key."""
import pytest

from textual.widgets import DataTable, Input, Static
from textual.binding import ModeBinding

from toad.application_actions import CommanderAction, KeymapAction
from toad.key_modes import KeyMode, Standard, VimInsert
from toad.preferences import SETTINGS, SavedSettings
from textual.document._editing import Escape, VimInsert as InsertEditing, VimNormal
from toad.screens.keymap import KeymapScreen
from toad.keymap import KeymapRow
from toad.widget_actions import ProfileKeys


class CallCounter(ProfileKeys, Static, can_focus=True):
    """One native callable with two default aliases, discovered without a view edit."""

    count = 0

    def increment(self) -> None:
        self.count += 1
        self.update(str(self.count))

    MODE_BINDINGS = (
        ModeBinding("f8", increment, "Increment", mode=Standard().binding_mode),
        ModeBinding("f9", increment, "Increment", mode=Standard().binding_mode),
    )


async def choose(ui, invocation, mode=Standard):
    screen = ui.app.screen
    screen.query_one("#keymap-search", Input).value = invocation.key_title()
    await ui.step()
    table = screen.query_one(DataTable)
    table.move_cursor(row=screen.visible_declarations.index(KeymapRow.of(invocation, mode).declaration),
                      column=screen.modes.index(mode) + 1)
    table.focus()
    await ui.press("enter")


@pytest.mark.parametrize("mode", KeyMode.members_with(KeyMode))
@pytest.mark.parametrize("size", ((140, 45), (83, 19)))
async def test_f1_menu_remaps_itself_saves_and_refuses_a_conflict(workspace, mode, size):
    async with workspace.app(size=size) as ui:
        app = ui.app
        app.saved_settings.set(SETTINGS.ui.key_mode, mode)
        ui.conversation.prompt.prompt_text_area.focus()
        await ui.step()
        await ui.press("f1")
        await ui.until(lambda: isinstance(app.screen, KeymapScreen), why="the keymap menu")
        table = app.screen.query_one(DataTable)
        assert table.size.height > table.header_height, "The command rows must have visible space"
        await choose(ui, KeymapAction(), mode)
        app.screen.query_one("#keymap-keys", Input).value = "f7"
        await ui.pilot.click("#keymap-apply")
        await ui.until(lambda: KeymapAction.binding_id(mode().binding_mode) in app._keymap,
                       why="the saved menu remap")
        document = app.saved_settings.document()
        assert SavedSettings(document).current.ui.keymap == app.settings.ui.keymap
        assert not app.saved_settings.unsaved
        app.screen.query_one("#keymap-search", Input).value = "Commander"
        await ui.step()
        app.screen.query_one("#keymap-keys", Input).value = "f6"
        await ui.pilot.click("#keymap-apply")
        assert app.saved_settings.document() == document, "Filtering must discard the previous cell selection"
        await ui.press("escape")
        await ui.until(lambda: app.screen is app.workspace_screen, why="the keymap menu closed")
        await ui.press("f1")
        assert app.screen is app.workspace_screen
        await ui.press("f7")
        await ui.until(lambda: isinstance(app.screen, KeymapScreen), why="the remapped menu key")
        await choose(ui, CommanderAction(), mode)
        app.screen.query_one("#keymap-keys", Input).value = "f7"
        await ui.pilot.click("#keymap-apply")
        await ui.until(lambda: "Key conflict" in str(app.screen.query_one("#keymap-status", Static).render()),
                       why="the colliding remap refusal")
        assert app.saved_settings.document() == document
        assert "Commander" in str(app.screen.query_one("#keymap-status", Static).render())
        assert "Keymap" in str(app.screen.query_one("#keymap-status", Static).render())
    async with workspace.app(size=size) as reopened:
        await reopened.press("f1")
        assert reopened.app.screen is reopened.app.workspace_screen
        await reopened.press("f7")
        await reopened.until(lambda: isinstance(reopened.app.screen, KeymapScreen),
                             why="the saved menu remap after restarting the app")


async def test_the_menu_remaps_the_native_insert_escape_without_changing_normal(workspace):
    async with workspace.app(size=(140, 45)) as ui:
        app = ui.app
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        editor = ui.conversation.prompt.prompt_text_area
        editor.focus()
        await ui.press("f1")
        await ui.until(lambda: isinstance(app.screen, KeymapScreen), why="the native command menu")
        await choose(ui, Escape(), VimInsert)
        app.screen.query_one("#keymap-keys", Input).value = "f6"
        await ui.pilot.click("#keymap-apply")
        await ui.until(lambda: Escape.binding_id(InsertEditing) in app._keymap,
                       why="the native Insert escape override")
        await ui.press("escape")
        await ui.until(lambda: app.screen is app.workspace_screen, why="the menu dismissed")
        editor.focus()
        await ui.press("escape")
        assert isinstance(editor.editing_mode, InsertEditing)
        await ui.press("f6")
        assert type(editor.editing_mode) is VimNormal


async def test_the_menu_discovers_and_remaps_a_native_callable_with_both_aliases(workspace):
    async with workspace.app(size=(140, 45)) as ui:
        counter = CallCounter("0")
        await ui.app.screen.mount(counter)
        counter.focus()
        invocation = counter.MODE_BINDINGS[0].invocation
        row = KeymapRow.of(invocation, Standard)
        await ui.press("f1")
        await ui.until(lambda: isinstance(ui.app.screen, KeymapScreen), why="the native callable in the menu")
        catalog = ui.app.screen.catalog
        assert catalog.defaults(row) == ("f8", "f9")
        assert len(ui.app.screen.modes) == 4
        await choose(ui, invocation)
        ui.app.screen.query_one("#keymap-keys", Input).value = "f6"
        await ui.pilot.click("#keymap-apply")
        await ui.until(lambda: catalog.effective(row, ui.app.settings.ui.keymap) == ("f6",),
                       why="the saved callable remap")
        loaded = SavedSettings(ui.app.saved_settings.document()).current.ui.keymap
        assert catalog.effective(row, loaded) == ("f6",)
        await ui.press("escape")
        counter.focus()
        await ui.press("f8", "f9")
        assert counter.count == 0
        await ui.press("f6")
        assert counter.count == 1
