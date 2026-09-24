"""Drive Toad's menu into real core export and stopped-thread import operations."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, ThreadStatus
from runtime_fixture import ToadApp
from textual.widgets import Input, Select, Static

from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_transfer import ThreadImportDialog, WireExportDialog
from toad.widgets.side_bar import MainMenuButton, TabHistoryButton, TabHistoryControls


async def wait_for(pilot, predicate) -> None:
    async with asyncio.timeout(10):
        while not predicate():
            await pilot.pause(.05)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-main-menu-transfer-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        comms = app.coordination_wire
        comms.register(Thread("sender", frozenset(), str(root)))
        comms.send("sender", "#all", "exported message")

        source = root / "source.json"
        source.write_text(json.dumps({
            "info": {"id": "ses_test", "directory": str(root), "title": "Imported session"},
            "messages": [{"info": {"id": "user", "role": "user"},
                          "parts": [{"type": "text", "text": "Imported history"}]}],
        }))
        destination = root / "export.jsonl"

        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            controls = app.screen.query_one(TabHistoryControls)
            assert [type(item) for item in controls.children] == [
                MainMenuButton, TabHistoryButton, TabHistoryButton,
            ], "Main menu must be left of Back and Forward"

            controls.query_one(MainMenuButton).action_open_menu()
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, ContextMenu)
            menu.action_choose()
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, WireExportDialog)
            dialog.query_one("#export-scope", Select).value = "channel"
            dialog.action_submit()
            assert "requires one #channel" in dialog.query_one("#transfer-error", Static).render().plain
            dialog.query_one("#export-scope", Select).value = "everything"
            dialog.query_one("#export-path", Input).value = str(destination)
            dialog.action_submit()
            await wait_for(pilot, destination.exists)
            rows = [json.loads(line) for line in destination.read_text().splitlines()]
            assert rows[0]["record"] == "header"
            assert [row["message"]["text"] for row in rows[1:]] == ["exported message"]

            await wait_for(pilot, lambda: app.screen.query_one_optional(MainMenuButton) is not None)
            app.screen.query_one(MainMenuButton).action_open_menu()
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, ContextMenu)
            list(menu.query(ContextMenuItem))[1].focus()
            await pilot.pause()
            assert isinstance(menu.focused, ContextMenuItem) and menu.focused.action == "import", (
                "Import must be the second main-menu choice",
                getattr(menu.focused, "action", None),
            )
            menu.action_choose()
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, ThreadImportDialog), type(dialog)
            dialog.query_one("#import-source", Input).value = str(source)
            dialog.query_one("#import-name", Input).value = "imported"
            dialog.action_submit()
            await wait_for(pilot, lambda: comms.registry.name_reserved("imported"))
            thread = comms.registry.require("imported")
            assert comms.registry.status(thread.name) is ThreadStatus.STOPPED
            assert "Imported history" in Path(thread.session_file).read_text()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("Toad main menu: export JSONL and import stopped thread through core operations")


if __name__ == "__main__":
    asyncio.run(main())
