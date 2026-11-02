"""Textual-facing: the main menu button opens Toad's menu and its dialogs drive Core's wire export and stopped-thread import."""

import json
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Select
from agent_comms.exporting import EverythingScope, FullLimit, JsonlFormat, TextFormat, WireExportCancelled, WireExportProgress
from agent_comms.messages import InfoKind, Message, PublicRecord
from support.workspace import Workspace

from agent_comms.harness_install import OpenCodeHarness
from support.applications import record_notifications
from toad.widget_actions import ApplicationAction
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.comms_transfer import (
    ChannelScopeInput, EverythingScopeInput, JsonlFormatInput, TextFormatInput,
    ThreadImportDialog, WireExportDialog, WireExportProgressView, WireExportRequest,
)
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


async def choose(ui, menu, label: str):
    """The menu shows every offered application action in declaration order; reach ``label``
    with the arrow keys and press enter, as a user does."""
    options = menu.options
    shown = [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]
    assert shown == [label for _, label in ApplicationAction.menu(ui.textual[0])]
    assert shown[0] == "New thread" and shown[-1] == "Quit"
    await ui.press(*["down"] * shown.index(label), "enter")


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
        app.screen.query_one("#export-scope", Select).value = ChannelScopeInput
        app.screen.action_submit()
        await ui.until(lambda: any(note.title == "Wire export failed" and "Unknown channel" in note.message
                                   for note in app._notifications), why="the export refusal")
        assert not app.screen.query(WireExportProgressView), "the failed export must remove its progress resource"
        await choose(ui, await open_main_menu(ui), "Export wire history…")
        await ui.until(lambda: isinstance(app.screen, WireExportDialog), why="the export dialog")
        dialog = app.screen
        dialog.query_one("#export-scope", Select).value = EverythingScopeInput
        dialog.query_one("#export-path", Input).value = str(destination)
        dialog.action_submit()
        await ui.until(destination.exists, seconds=10, why="the export file")
        rows = [json.loads(line) for line in destination.read_text().splitlines()]
        assert rows[0]["record"] == "header"
        assert [row["message"]["text"] for row in rows[1:]] == ["exported message"]
        await ui.until(lambda: any(note.title == "Wire export" and str(destination) in note.message
                                   for note in app._notifications), why="the completed export notification")
        assert not app.screen.query(WireExportProgressView), "completion removes the actual progress widget"


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
        record_notifications(ui.textual[0])
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
        assert "Imported history" in Path(thread.runtime.path).read_text()
        await ui.until(lambda: any(note.title == "Thread Import" and "@imported" in note.message
                                   for note in ui.textual[0]._notifications), why="the import completion")
        assert not ui.textual[0].screen.query(WireExportProgressView), "imports do not allocate export cancellation"


async def test_export_format_updates_only_the_generated_destination(workspace):
    async with workspace.app(size=(110, 40)) as ui:
        app, _ = ui.textual
        await choose(ui, await open_main_menu(ui), "Export wire history…")
        await ui.until(lambda: isinstance(app.screen, WireExportDialog), why="the export dialog")
        dialog = app.screen
        assert dialog.format_select.selection is JsonlFormatInput
        dialog.format_select.value = TextFormatInput
        await ui.until(lambda: dialog.destination_input.value == str(TextFormatInput.destination(dialog.destination_stem)),
                       why="the text format's generated destination")
        custom = str(workspace.project / "custom-output.log")
        dialog.destination_input.value = custom
        dialog.format_select.value = JsonlFormatInput
        await ui.press("tab")
        assert dialog.format_select.selection is JsonlFormatInput
        assert dialog.destination_input.value == custom, "format changes must retain the user's chosen path"


async def test_export_progress_presents_counters_and_native_cancel(workspace):
    """Exercise the real progress capability/view, not exporter or staging acceptance."""
    async with workspace.app(size=(110, 40)) as ui:
        app, _ = ui.textual
        request = WireExportRequest(workspace.project / "unused.jsonl", JsonlFormat(), EverythingScope(), FullLimit())
        async with request.progress(app) as observer:
            progress = app.screen.query_one(WireExportProgressView)
            assert observer is progress
            observer.advanced(WireExportProgress(bytes_written=4096, messages_written=7))
            await ui.until_shows("7 messages · 4,096 bytes written")
            await ui.click("Cancel export")
            await ui.until(progress.cancelled, why="the exporter's actual cancellation event")
            assert progress.query_one("#cancel-export", Button).disabled
            with pytest.raises(WireExportCancelled):
                observer.check()
        assert progress.parent is None, "the actual mounted resource must be detached"
        assert not app.screen.query(WireExportProgressView)
        assert not request.destination.exists(), "this case supplies progress observations, never a fake export"


@pytest.mark.parametrize("close_app", (False, True), ids=("native-cancel", "app-close"))
async def test_running_export_retires_writer_and_staging(workspace: Workspace, close_app: bool):
    """A real indexed wire and real writer, without replacing exporter or preparation methods."""
    workspace.thread("sender")
    wire = workspace.comms.bus.bus
    payload = "running-export-row " + "x" * 32768
    for _ in range(2048):
        wire.append(lambda seq, db: PublicRecord.from_message(
            Message("sender", "#all", payload, InfoKind, seq=seq)))
    print("Seeded 2048 indexed wire records for running-writer acceptance", flush=True)
    destination = workspace.project / "running-export.txt"
    protected = workspace.project / "existing-export.txt"
    protected.write_bytes(b"preserve the existing destination\n")
    original = protected.read_bytes()

    async with workspace.app(size=(110, 40)) as ui:
        app, _ = ui.textual
        record_notifications(app)
        access = app.coordination_access
        selected = access.selected(access.observation.observed().service.root)
        app.transfer_submitted(selected, WireExportRequest(
            protected, TextFormat(), EverythingScope(), FullLimit()))
        await ui.until(lambda: any(note.title == "Wire export failed" for note in app._notifications),
                       why="refusal of the pre-existing destination")
        assert protected.read_bytes() == original
        assert not list(protected.parent.glob(".existing-export.txt.*.tmp"))

        request = WireExportRequest(destination, TextFormat(), EverythingScope(), FullLimit())
        worker = app.run_worker(request.execute(app, selected),
                                group=type(request).declared_name, exclusive=True)

        def writing() -> bool:
            assert not destination.exists(), "the case must reach the writer before publication"
            return any(path.stat().st_size > 65536
                       for path in destination.parent.glob(".running-export.txt.*.tmp"))

        await ui.until(writing, why="actual bytes flushed to the writer's private stage")
        progress = app.screen.query_one(WireExportProgressView)
        assert not worker.is_finished
        # Ordinary wire traffic still uses the authoritative publisher while
        # the export holds its fixed read snapshot and streams the old rows.
        sent = workspace.comms.messaging.send("sender", "#all", "sent during export").message
        assert wire.lookup(sent.seq).body == "sent during export"
        assert not worker.is_finished, "the ordinary send must overlap the running writer"
        print("Observed live staging and an overlapping ordinary send", flush=True)
        if close_app:
            app.exit()
        else:
            # The separate view case checks the pointer path; this invokes the
            # same native Button activation while the actual writer is alive.
            progress.query_one("#cancel-export", Button).press()
            await ui.until(lambda: worker.is_finished, why="the real cancelled writer to finish")
            assert progress.cancelled()
            await ui.until(lambda: any(note.message == "Wire export cancelled"
                                      for note in app._notifications), why="actual export cancellation")
            assert progress.parent is None

    assert worker.is_finished, "application release must join accepted export work"
    assert not destination.exists(), "cancel/close must not publish the interrupted export"
    assert not list(destination.parent.glob(".running-export.txt.*.tmp")), "private staging must unwind"
    assert protected.read_bytes() == original
    print("Writer finished; private staging removed; existing destination unchanged", flush=True)
