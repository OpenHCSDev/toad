"""The menu edits saved mode-specific bindings, including its own opening key."""
from textual.widgets import DataTable, Input, Static

from toad.application_actions import CommanderAction, KeymapAction
from toad.key_modes import Standard, VimInsert
from toad.preferences import SETTINGS, SavedSettings
from textual.document._editing import Escape, VimInsert as InsertEditing, VimNormal
from toad.screens.keymap import KeymapScreen


async def choose(ui, declaration, mode=Standard):
    screen = ui.app.screen
    screen.query_one("#keymap-search", Input).value = declaration.title
    await ui.step()
    table = screen.query_one(DataTable)
    table.move_cursor(row=screen.visible_declarations.index(declaration), column=screen.modes.index(mode) + 1)
    table.focus()
    await ui.press("enter")


async def test_f1_menu_remaps_itself_saves_and_refuses_a_conflict(workspace):
    async with workspace.app(size=(140, 45)) as ui:
        app = ui.app
        await ui.press("f1")
        await ui.until(lambda: isinstance(app.screen, KeymapScreen), why="the keymap menu")
        await choose(ui, KeymapAction)
        app.screen.query_one("#keymap-keys", Input).value = "f7"
        await ui.pilot.click("#keymap-apply")
        await ui.until(lambda: KeymapAction.binding_id(Standard().binding_mode) in app._keymap,
                       why="the saved menu remap")
        document = app.saved_settings.document()
        assert SavedSettings(document).current.ui.keymap == app.settings.ui.keymap
        assert not app.saved_settings.unsaved
        await ui.press("escape")
        await ui.until(lambda: app.screen is app.workspace_screen, why="the keymap menu closed")
        await ui.press("f1")
        assert app.screen is app.workspace_screen
        await ui.press("f7")
        await ui.until(lambda: isinstance(app.screen, KeymapScreen), why="the remapped menu key")
        await choose(ui, CommanderAction)
        app.screen.query_one("#keymap-keys", Input).value = "f7"
        await ui.pilot.click("#keymap-apply")
        await ui.until(lambda: "Key conflict" in str(app.screen.query_one("#keymap-status", Static).render()),
                       why="the colliding remap refusal")
        assert app.saved_settings.document() == document
        assert "Commander" in str(app.screen.query_one("#keymap-status", Static).render())
        assert "Keymap" in str(app.screen.query_one("#keymap-status", Static).render())
    async with workspace.app(size=(140, 45)) as reopened:
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
        await choose(ui, Escape, VimInsert)
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
