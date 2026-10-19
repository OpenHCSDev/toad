"""Textual-facing: the main menu button opens Toad's menu and its dialogs drive Core's wire export and stopped-thread import."""

import json
from pathlib import Path

from textual.widgets import Input, Select

from agent_comms.harness_install import OpenCodeHarness
from support.applications import record_notifications
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.comms_transfer import ThreadImportDialog, WireExportDialog
from toad.widgets.side_bar import BackTabButton, ForwardTabButton, MainMenuButton, TabHistoryControls


async def open_main_menu(ui):
    app, _ = ui.textual
    await ui.until(lambda: app.screen.query_one_optional(MainMenuButton) is not None, why="the main menu button")
    app.screen.query_one(MainMenuButton).open_menu()
    await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the menu")
    # The menu's native option list takes focus with its first choice highlighted.
    menu = app.screen
    await ui.until(lambda: menu.focused is menu.options and menu.options.highlighted == 0,
                   why="the menu's first choice focused")
    return menu


# PR #759 (29faa049) declared the application menu in this order.
MENU = ["New thread", "Settings", "Export wire history…", "Thread Import…", "Exit"]


async def choose(ui, menu, label: str):
    """Assert the declared menu, then reach ``label`` with the arrow keys and press enter, as a user does."""
    options = menu.options
    assert [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)] == MENU
    await ui.press(*["down"] * MENU.index(label), "enter")


async def test_main_menu_sits_left_of_back_and_forward(workspace):
    async with workspace.app(size=(110, 40)) as ui:
        app, _ = ui.textual
        controls = app.screen.query_one(TabHistoryControls)
        assert [type(item) for item in controls.children] == [
            MainMenuButton, BackTabButton, ForwardTabButton,
        ], "Main menu must be left of Back and Forward"


async def test_main_menu_exports_the_wire_as_jsonl(workspace):
    workspace.thread("sender")
    workspace.comms.messaging.send("sender", "#all", "exported message")
    destination = workspace.project / "export.jsonl"
    async with workspace.app(size=(110, 40)) as ui:
        app, _ = ui.textual
        record_notifications(app)
        # Core 95b517678 deleted the scope's construction refusal on purpose: the
        # export operation resolves the channel and refuses an unknown one.
        await choose(ui, await open_main_menu(ui), "Export wire history…")
        await ui.until(lambda: isinstance(app.screen, WireExportDialog), why="the export dialog")
        app.screen.query_one("#export-scope", Select).value = "channel"
        app.screen.action_submit()
        await ui.until(lambda: any(note.title == "Wire export failed" and "Unknown channel" in note.message
                                   for note in app._notifications), why="the export refusal")
        await choose(ui, await open_main_menu(ui), "Export wire history…")
        await ui.until(lambda: isinstance(app.screen, WireExportDialog), why="the export dialog")
        dialog = app.screen
        dialog.query_one("#export-scope", Select).value = "everything"
        dialog.query_one("#export-path", Input).value = str(destination)
        dialog.action_submit()
        await ui.until(destination.exists, seconds=10, why="the export file")
        rows = [json.loads(line) for line in destination.read_text().splitlines()]
        assert rows[0]["record"] == "header"
        assert [row["message"]["text"] for row in rows[1:]] == ["exported message"]


async def test_main_menu_imports_a_session_as_a_stopped_thread(workspace):
    source = workspace.project / "source.json"
    source.write_text(json.dumps({
        "info": {"id": "ses_test", "directory": str(workspace.project), "title": "Imported session"},
        # OpenCode's saved export as Core declares it (05274ec7d).
        "messages": [{"info": {"id": "user", "sessionID": "ses_test", "role": "user", "time": {"created": 1}},
                      "parts": [{"id": "user-0", "sessionID": "ses_test", "messageID": "user",
                                 "type": "text", "text": "Imported history"}]}],
    }))
    comms = workspace.comms
    async with workspace.app(size=(110, 40)) as ui:
        menu = await open_main_menu(ui)
        await choose(ui, menu, "Thread Import…")
        await ui.until(lambda: isinstance(ui.textual[0].screen, ThreadImportDialog), why="the import dialog")
        dialog = ui.textual[0].screen
        # 23331e21 replaced the deleted ImportFormat with Core's Harness family on purpose.
        dialog.query_one("#import-harness", Select).value = OpenCodeHarness
        dialog.query_one("#import-source", Input).value = str(source)
        dialog.query_one("#import-name", Input).value = "imported"
        dialog.action_submit()
        await ui.until(lambda: comms.registry.snapshot().taken("imported"), seconds=10, why="the imported thread")
        thread = comms.registry.require("imported")
        assert comms.registry.status(thread.name).stopped
        assert "Imported history" in Path(thread.session_file).read_text()
