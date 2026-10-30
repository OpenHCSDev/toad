"""Inputs for the existing agent-comms export and thread-import operations."""

from __future__ import annotations
from toad.core import events as core_events

from dataclasses import dataclass
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from time import monotonic
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
import asyncio
from functools import partial
from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.comms import Comms
from agent_comms.cli_result import CliResult
from agent_comms.importing import ThreadImported
from agent_comms.field_codec import FieldCodec
from agent_comms.route_selection import RouteSelection

from agent_comms.exporting import (
    CancellableWireExport,
    WireExportCancelled,
    WireExportObserver,
    WireExportProgress,
    WireExportProvenance,
    ChannelScope,
    DmScope,
    EverythingScope,
    FullLimit,
    MaxBytesLimit,
    WireExportFormat,
    WireExportLimit,
    WireExportScope,
)
from agent_comms.cli_bridges.history import ExpectedSession, OfflineHistory
from agent_comms.harness_install import Harness
from agent_comms.thread_management import ImportDirectory
from textual import on
from textual.app import App, ComposeResult
from textual.message import Message
from textual.containers import Vertical
from toad.screens.modal import DismissibleScreen
from toad.comms_root import CoordinationAccess
from toad.application_lifetime import TerminalOutcome
from toad.widget_actions import DismissAction
from textual.widgets import Button, Input, Select, Static


class TransferProgress(WireExportObserver):
    """The shared progress capability does not make an operation cancellable."""

    def cancel(self) -> None:
        pass


class TransferRequest(DeclaredFamily, affix="Request"):
    """Declaration order is the order of the application menu's transfer entries."""

    failure_title: ClassVar[str]
    title: ClassVar[str]
    cancelled_by: ClassVar[tuple[type[BaseException], ...]] = ()

    @classmethod
    @abstractmethod
    def dialog(cls, selected: RouteSelection): ...

    @abstractmethod
    def apply(self, comms: Comms, observer: TransferProgress) -> CliResult: ...

    def execute(self, access: CoordinationAccess, selected: RouteSelection,
                observer: TransferProgress) -> CliResult:
        comms = access.require(selected).service
        return access.write(selected, self.apply, comms, observer)

    @asynccontextmanager
    async def progress(self, app: App[TerminalOutcome]) -> AsyncIterator[TransferProgress]:
        yield TransferProgress()

    def cancelled(self, app: App[TerminalOutcome]) -> None:
        pass

    @abstractmethod
    def completed(self, app, result) -> None: ...


@dataclass(frozen=True)
class WireExportRequest(TransferRequest):
    destination: Path
    format: WireExportFormat
    scope: WireExportScope
    limit: WireExportLimit

    failure_title = "Wire export failed"
    title = "Export wire history…"
    cancelled_by = (WireExportCancelled,)

    @classmethod
    def dialog(cls, selected):
        return WireExportDialog(selected.root)

    def apply(self, comms: Comms, observer: TransferProgress) -> WireExportProvenance:
        return comms.views.export_wire(self.destination, format=self.format, scope=self.scope,
                                       limit=self.limit, observer=observer)

    def execute(self, access: CoordinationAccess, selected: RouteSelection,
                observer: TransferProgress) -> WireExportProvenance:
        return self.apply(access.require(selected).service, observer)

    @asynccontextmanager
    async def progress(self, app: App[TerminalOutcome]) -> AsyncIterator[TransferProgress]:
        progress = WireExportProgressView()
        await app.mount(progress)
        try:
            yield progress
        finally:
            if progress.is_mounted:
                await progress.remove()

    def cancelled(self, app: App[TerminalOutcome]) -> None:
        app.notify("Wire export cancelled", title="Wire export")

    def completed(self, app, result) -> None:
        app.notify(f"Exported {result.exported_messages} messages to {result.destination}", title="Wire export")


@dataclass(frozen=True)
class ThreadImportRequest(TransferRequest):
    source: Path
    harness: type[Harness]
    name: str
    session: ExpectedSession
    worktree: ImportDirectory

    failure_title = "Thread import failed"
    title = "Thread Import…"

    @classmethod
    def dialog(cls, selected):
        return ThreadImportDialog()

    def apply(self, comms: Comms, observer: TransferProgress) -> ThreadImported:
        return comms.threads.import_thread(OfflineHistory.stored(self.harness, self.source, self.session),
                                          name=self.name, worktree=self.worktree)

    def completed(self, app, result) -> None:
        app.events.publish(core_events.ThreadRowStateChanged(frozenset((result.thread,))))
        app.notify(f"Imported @{result.thread} ({result.imported_messages} messages) as a stopped thread",
                   title="Thread Import")


class Transfers:
    def __init__(self, app) -> None:
        self.app = app

    def open(self, kind: type[TransferRequest]) -> None:
        access = self.app.coordination_access
        selected = access.selected(access.observation.observed().service.root)
        self.app.push_screen(kind.dialog(selected), callback=partial(self.submitted, selected))

    def submitted(self, selected: RouteSelection, request: TransferRequest | None) -> None:
        if request is not None:
            self.app.run_worker(partial(self.execute, selected, request),
                                group=FieldCodec.encode(type(request)), exclusive=True)

    async def execute(self, selected: RouteSelection, request: TransferRequest) -> None:
        try:
            async with request.progress(self.app) as observer:
                operation = asyncio.create_task(asyncio.to_thread(
                    request.execute, self.app.coordination_access, selected, observer))
                try:
                    result = await asyncio.shield(operation)
                except asyncio.CancelledError:
                    observer.cancel()
                    with suppress(*request.cancelled_by):
                        await asyncio.shield(operation)
                    raise
        except request.cancelled_by:
            request.cancelled(self.app)
            return
        except (OSError, ValueError) as error:
            self.app.show_error(error, request.failure_title)
            return
        request.completed(self.app, result)


class TransferDialog(DismissibleScreen):
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
    def _error(self, error: str) -> None:
        self.query_one("#transfer-error", Static).update(error)


class WireExportProgressView(CancellableWireExport, TransferProgress, Vertical):
    """The export's cancellation capability and a view of its own byte/message counters."""

    DEFAULT_CSS = """
    WireExportProgressView {
        position: absolute; overlay: screen; width: 64; max-width: 95%; height: auto;
        padding: 1 2; border: solid $primary; background: $surface;
    }
    """

    @dataclass
    class Updated(Message):
        progress: WireExportProgress

    def __init__(self) -> None:
        super().__init__()
        self.last_report = 0.0

    def compose(self) -> ComposeResult:
        yield Static("Exporting wire history")
        yield Static("0 messages · 0 bytes written", id="export-progress")
        yield Button("Cancel export", id="cancel-export")

    def advanced(self, progress: WireExportProgress) -> None:
        now = monotonic()
        if now - self.last_report >= 0.1:
            self.last_report = now
            self.post_message(self.Updated(progress))

    @on(Updated)
    def update_progress(self, event: Updated) -> None:
        progress = event.progress
        self.query_one("#export-progress", Static).update(
            f"{progress.messages_written:,} messages · {progress.bytes_written:,} bytes written")

    @on(Button.Pressed, "#cancel-export")
    def cancel_export(self) -> None:
        self.cancel()
        button = self.query_one("#cancel-export", Button)
        button.label = "Cancelling…"
        button.disabled = True

    def on_unmount(self) -> None:
        self.cancel()


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
            yield Button("Cancel", id="cancel-transfer", action=f"screen.{DismissAction.binding_name()}")

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
                WireExportFormat.member_named(self.query_one("#export-format", Select).value)(),
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
            yield Static("Thread Import: a stored harness session")
            harnesses = Harness.members_with(Harness)
            yield Select(
                [(harness.declared_name, harness) for harness in harnesses],
                value=harnesses[0], id="import-harness", allow_blank=False,
            )
            yield Input(id="import-source", placeholder="Source JSON, database or rollout JSONL")
            yield Input(id="import-name", placeholder="New thread name")
            yield Input(id="import-session-id", placeholder="Session ID (OpenCode database only)")
            yield Input(id="import-worktree", placeholder="Project directory override (optional)")
            yield Static("", id="transfer-error")
            yield Button("Import stopped thread", id="submit-transfer")
            yield Button("Cancel", id="cancel-transfer", action=f"screen.{DismissAction.binding_name()}")

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
            self.query_one("#import-harness", Select).value,
            name,
            FieldCodec.decode(ExpectedSession, self.query_one("#import-session-id", Input).value.strip() or None),
            FieldCodec.decode(ImportDirectory, self.query_one("#import-worktree", Input).value.strip() or None),
        ))
