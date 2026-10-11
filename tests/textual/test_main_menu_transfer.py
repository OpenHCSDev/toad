"""Textual-facing: the main menu button opens Toad's menu and its dialogs drive Core's wire export and stopped-thread import."""

import json
from pathlib import Path

from textual.widgets import Input, Select, Static

from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_transfer import ThreadImportDialog, ThreadImportRequest, WireExportDialog
from toad.widgets.side_bar import MainMenuButton, TabHistoryButton, TabHistoryControls


async def open_main_menu(ui):
    app, _ = ui.textual
    await ui.until(lambda: app.screen.query_one_optional(MainMenuButton) is not None, why="the main menu button")
    app.screen.query_one(MainMenuButton).action_open_menu()
    await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the menu")
    return app.screen


async def test_main_menu_sits_left_of_back_and_forward(workspace):
    async with workspace.app(size=(110, 40)) as ui:
        app, _ = ui.textual
        controls = app.screen.query_one(TabHistoryControls)
        assert [type(item) for item in controls.children] == [
            MainMenuButton, TabHistoryButton, TabHistoryButton,
        ], "Main menu must be left of Back and Forward"


async def test_main_menu_exports_the_wire_as_jsonl(workspace):
    workspace.thread("sender")
    workspace.comms.messaging.send("sender", "#all", "exported message")
    destination = workspace.project / "export.jsonl"
    async with workspace.app(size=(110, 40)) as ui:
        menu = await open_main_menu(ui)
        menu.action_choose()
        await ui.until(lambda: isinstance(ui.textual[0].screen, WireExportDialog), why="the export dialog")
        dialog = ui.textual[0].screen
        dialog.query_one("#export-scope", Select).value = "channel"
        dialog.action_submit()
        assert "requires one #channel" in dialog.query_one("#transfer-error", Static).render().plain
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
        "messages": [{"info": {"id": "user", "role": "user"},
                      "parts": [{"type": "text", "text": "Imported history"}]}],
    }))
    comms = workspace.comms
    async with workspace.app(size=(110, 40)) as ui:
        menu = await open_main_menu(ui)
        list(menu.query(ContextMenuItem))[1].focus()
        await ui.step()
        assert isinstance(menu.focused, ContextMenuItem) and menu.focused.action == ThreadImportRequest.declared_name, (
            "Import must be the second main-menu choice", getattr(menu.focused, "action", None))
        menu.action_choose()
        await ui.until(lambda: isinstance(ui.textual[0].screen, ThreadImportDialog), why="the import dialog")
        dialog = ui.textual[0].screen
        await ui.until(lambda: dialog.query("#import-format") and dialog.query_one("#import-format", Select).value == "opencode",
                       why="the import dialog's format choice")
        dialog.query_one("#import-source", Input).value = str(source)
        dialog.query_one("#import-name", Input).value = "imported"
        dialog.action_submit()
        await ui.until(lambda: comms.registry.name_reserved("imported"), seconds=10, why="the imported thread")
        thread = comms.registry.require("imported")
        assert comms.registry.status(thread.name).stopped
        assert "Imported history" in Path(thread.session_file).read_text()
