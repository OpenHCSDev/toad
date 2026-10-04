"""Inputs for the existing agent-comms export and thread-import operations."""

from __future__ import annotations
from toad.core import events as core_events

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
import asyncio
from functools import partial
from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from toad.comms_root import RouteSelection

from agent_comms.exporting import (
    ChannelScope,
    DmScope,
    EverythingScope,
    FullLimit,
    MaxBytesLimit,
    WireExportFormat,
    WireExportLimit,
    WireExportScope,
)
from agent_comms.importing import ImportFormat
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static


class TransferRequest(DeclaredFamily, affix="Request"):
    failure_title: ClassVar[str]
    menu_label: ClassVar[str]
    menu_order: ClassVar[int]

    @classmethod
    def menu(cls):
        return tuple(sorted(cls.members_with(cls), key=lambda request: request.menu_order))

    @classmethod
    @abstractmethod
    def dialog(cls, selected: RouteSelection): ...

    @abstractmethod
    def apply(self, comms): ...

    @abstractmethod
    def completed(self, app, receipt) -> None: ...


@dataclass(frozen=True)
class WireExportRequest(TransferRequest):
    destination: Path
    format: WireExportFormat
    scope: WireExportScope
    limit: WireExportLimit

    failure_title = "Wire export failed"
    menu_label = "Export wire history…"
    menu_order = 0

    @classmethod
    def dialog(cls, selected):
        return WireExportDialog(selected.root)

    def apply(self, comms):
        return comms.views.export_wire(self.destination, format=self.format, scope=self.scope, limit=self.limit)

    def completed(self, app, receipt) -> None:
        app.notify(f"Exported {receipt.exported_messages} messages to {receipt.destination}", title="Wire export")


@dataclass(frozen=True)
class ThreadImportRequest(TransferRequest):
    source: Path
    format: ImportFormat
    name: str
    session_id: str | None
    worktree: str | None

    failure_title = "Thread import failed"
    menu_label = "Thread Import…"
    menu_order = 1

    @classmethod
    def dialog(cls, selected):
        return ThreadImportDialog()

    def apply(self, comms):
        return comms.threads.import_thread(self.source, self.format, name=self.name,
                                          session_id=self.session_id, worktree=self.worktree)

    def completed(self, app, receipt) -> None:
        app.events.publish(core_events.ThreadActionsChanged())
        app.notify(f"Imported @{receipt.thread} ({receipt.imported_messages} messages) as a stopped thread",
                   title="Thread Import")


class Transfers:
    def __init__(self, app) -> None:
        self.app = app

    def open(self, kind: type[TransferRequest]) -> None:
        selected = RouteSelection.capture(self.app.coordination_access.service.root)
        self.app.push_screen(kind.dialog(selected), callback=partial(self.submitted, selected))

    def submitted(self, selected: RouteSelection, request: TransferRequest | None) -> None:
        if request is not None:
            self.app.run_worker(partial(self.execute, selected, request),
                                group=FieldCodec.encode(type(request)), exclusive=True, exit_on_error=False)

    async def execute(self, selected: RouteSelection, request: TransferRequest) -> None:
        try:
            comms = self.app.coordination_access.require(selected)
            receipt = await asyncio.to_thread(self.app.coordination_access.write, selected, request.apply, comms)
        except Exception as error:
            self.app.notify(str(error), title=request.failure_title, severity="error")
        else:
            request.completed(self.app, receipt)


class TransferDialog(ModalScreen):
    DEFAULT_CSS = """
    TransferDialog { align: center middle; background: $background 40%; }
    TransferDialog #transfer-box {
        width: 72; max-width: 95%; height: auto; max-height: 95%;
        padding: 1 2; border: solid $primary; background: $surface;
    }
    TransferDialog Input, TransferDialog Select { width: 1fr; margin-bottom: 1; }
    TransferDialog .transfer-actions { height: auto; width: 1fr; }
    TransferDialog #transfer-error { color: $error; height: auto; }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel-transfer")
    def on_cancel(self) -> None:
        self.dismiss(None)

    def _error(self, error: str) -> None:
        self.query_one("#transfer-error", Static).update(error)


class WireExportDialog(TransferDialog):
    """Select destination, representation, scope and an explicit size ceiling."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.default_path = root / "exports" / f"wire-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.jsonl"

    def compose(self) -> ComposeResult:
        with Vertical(id="transfer-box"):
            yield Static("Export wire history (not a Pi session)")
            yield Input(str(self.default_path), id="export-path", placeholder="Destination path")
            yield Select(
                [("JSON Lines (portable wire)", "jsonl"), ("Readable text", "text")],
                value="jsonl", id="export-format", allow_blank=False,
            )
            yield Select(
                [("Everything", "everything"), ("One channel", "channel"),
                 ("One DM", "dm")],
                value="everything", id="export-scope", allow_blank=False,
            )
            yield Input(id="export-target", placeholder="#channel or first,second (for DM)")
            yield Input("5242880", id="export-limit", placeholder="Max bytes; empty = full")
            yield Static("", id="transfer-error")
            yield Button("Export", id="submit-transfer")
            yield Button("Cancel", id="cancel-transfer")

    def on_mount(self) -> None:
        self.query_one("#export-path", Input).focus()

    @on(Select.Changed, "#export-format")
    def on_format_changed(self, event: Select.Changed) -> None:
        path = self.query_one_optional("#export-path", Input)
        if path is not None and path.value in {
            str(self.default_path), str(self.default_path.with_suffix(".txt"))
        }:
            path.value = str(
                self.default_path.with_suffix(".txt")
                if event.value == "text" else self.default_path
            )

    @on(Button.Pressed, "#submit-transfer")
    def action_submit(self) -> None:
        try:
            path = self.query_one("#export-path", Input).value.strip()
            if not path:
                raise ValueError("Choose an output path.")
            kind = self.query_one("#export-scope", Select).value
            target = self.query_one("#export-target", Input).value.strip()
            if kind == "channel":
                scope = ChannelScope(target)
            elif kind == "dm":
                participants = [name.strip().removeprefix("@") for name in target.split(",")]
                scope = DmScope(tuple(participants))
            else:
                scope = EverythingScope()
            value = self.query_one("#export-limit", Input).value.strip()
            limit = MaxBytesLimit(int(value)) if value else FullLimit()
            request = WireExportRequest(
                Path(path).expanduser(),
                WireExportFormat.decode(self.query_one("#export-format", Select).value)(),
                scope, limit,
            )
        except (TypeError, ValueError) as error:
            self._error(str(error))
            return
        self.dismiss(request)


class ThreadImportDialog(TransferDialog):
    """Create one stopped, resumable thread from OpenCode or Codex history."""

    def compose(self) -> ComposeResult:
        with Vertical(id="transfer-box"):
            yield Static("Thread Import: OpenCode export/database or Codex rollout")
            yield Select(
                [("OpenCode", "opencode"), ("Codex", "codex")],
                value="opencode", id="import-format", allow_blank=False,
            )
            yield Input(id="import-source", placeholder="Source JSON, database or rollout JSONL")
            yield Input(id="import-name", placeholder="New thread name")
            yield Input(id="import-session-id", placeholder="Session ID (OpenCode database only)")
            yield Input(id="import-worktree", placeholder="Project directory override (optional)")
            yield Static("", id="transfer-error")
            yield Button("Import stopped thread", id="submit-transfer")
            yield Button("Cancel", id="cancel-transfer")

    def on_mount(self) -> None:
        self.query_one("#import-source", Input).focus()

    @on(Button.Pressed, "#submit-transfer")
    def action_submit(self) -> None:
        source = self.query_one("#import-source", Input).value.strip()
        name = self.query_one("#import-name", Input).value.strip()
        if not source or not name:
            self._error("A source and a new thread name are required.")
            return
        self.dismiss(ThreadImportRequest(
            Path(source).expanduser(),
            ImportFormat(self.query_one("#import-format", Select).value),
            name,
            self.query_one("#import-session-id", Input).value.strip() or None,
            self.query_one("#import-worktree", Input).value.strip() or None,
        ))
