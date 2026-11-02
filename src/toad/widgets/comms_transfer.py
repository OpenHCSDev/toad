"""Inputs for the existing agent-comms export and thread-import operations."""

from toad.core import events as core_events

from dataclasses import dataclass
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
import asyncio
from functools import cached_property, partial
from abc import abstractmethod
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec, boundary_decoder
from agent_comms.comms import Comms
from agent_comms.cli_result import CliResult
from agent_comms.importing import ThreadImported
from agent_comms.route_selection import RouteSelection

from agent_comms.exporting import (
    CancellableWireExport,
    WireExportCancelled,
    WireExportObserver,
    WireExportProgress,
    WireExportProvenance,
    JsonlFormat,
    TextFormat,
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
from toad.textual_colours import ThemedApp
from toad.work_preparation import PreparationRuntime
from toad.widget_actions import DismissAction
from textual.widgets import Button, Input, Select, Static
from textual.color import Color
from textual.css._style_properties import Edges
from textual.css.scalar import Scalar, Unit
from textual.geometry import Spacing
from ui_theme.scheme import ForegroundColour, PrimaryColour, SurfaceColour
from toad.app_node import ToadNode
from toad.widget_view import WidgetView


class TransferProgress(WireExportObserver):
    """The shared progress capability does not make an operation cancellable."""

    def cancel(self) -> None:
        pass


class Transfer(DeclaredFamily, affix="Request"):
    """The menu consumes a transfer, without interpreting its result type."""

    title: ClassVar[str]

    @classmethod
    @abstractmethod
    def dialog(cls, selected: RouteSelection) -> TransferDialog: ...

    @abstractmethod
    async def execute(self, app: Transfers, selected: RouteSelection) -> None: ...


class TransferRequest[Result: CliResult](Transfer):
    """One preparation lifetime carries each operation's own typed result."""

    failure_title: ClassVar[str]
    cancelled_by: ClassVar[tuple[type[BaseException], ...]] = ()

    @abstractmethod
    def apply(self, comms: Comms, observer: TransferProgress) -> Result: ...

    def perform(self, access: CoordinationAccess, selected: RouteSelection,
                observer: TransferProgress) -> Result:
        comms = access.require(selected).service
        return access.write(selected, self.apply, comms, observer)

    async def execute(self, app: Transfers, selected: RouteSelection) -> None:
        try:
            async with self.progress(app) as observer:
                try:
                    result = await app.preparation.run_thread(
                        self.perform, app.coordination_access, selected, observer)
                except asyncio.CancelledError:
                    observer.cancel()
                    raise
        except self.cancelled_by:
            self.cancelled(app)
            return
        except (OSError, ValueError) as error:
            app.show_error(error, self.failure_title)
            return
        self.completed(app, result)

    @asynccontextmanager
    async def progress(self, app: App[TerminalOutcome]) -> AsyncIterator[TransferProgress]:
        yield TransferProgress()

    def cancelled(self, app: App[TerminalOutcome]) -> None:
        pass

    @abstractmethod
    def completed(self, app: Transfers, result: Result) -> None: ...


@dataclass(frozen=True)
class WireExportRequest(TransferRequest[WireExportProvenance]):
    destination: Path
    format: WireExportFormat
    scope: WireExportScope
    limit: WireExportLimit

    failure_title = "Wire export failed"
    title = "Export wire history…"
    cancelled_by = (WireExportCancelled,)

    @classmethod
    def dialog(cls, selected: RouteSelection) -> WireExportDialog:
        return WireExportDialog(selected.root)

    def apply(self, comms: Comms, observer: TransferProgress) -> WireExportProvenance:
        return comms.views.export_wire(self.destination, format=self.format, scope=self.scope,
                                       limit=self.limit, observer=observer)

    def perform(self, access: CoordinationAccess, selected: RouteSelection,
                observer: TransferProgress) -> WireExportProvenance:
        return self.apply(access.require(selected).service, observer)

    @asynccontextmanager
    async def progress(self, app: App[TerminalOutcome]) -> AsyncIterator[TransferProgress]:
        progress = WireExportProgressView()
        try:
            await app.mount(progress)
            yield progress
        finally:
            progress.cancel()
            await progress.remove()

    def cancelled(self, app: App[TerminalOutcome]) -> None:
        app.notify("Wire export cancelled", title="Wire export")

    def completed(self, app: Transfers, result: WireExportProvenance) -> None:
        app.notify(f"Exported {result.exported_messages} messages to {result.destination}", title="Wire export")


@dataclass(frozen=True)
class ThreadImportRequest(TransferRequest[ThreadImported]):
    source: Path
    harness: type[Harness]
    name: str
    session: ExpectedSession
    worktree: ImportDirectory

    failure_title = "Thread import failed"
    title = "Thread Import…"

    @classmethod
    def dialog(cls, selected: RouteSelection) -> ThreadImportDialog:
        return ThreadImportDialog()

    def apply(self, comms: Comms, observer: TransferProgress) -> ThreadImported:
        return comms.threads.import_thread(OfflineHistory.stored(self.harness, self.source, self.session),
                                          name=self.name, worktree=self.worktree)

    def completed(self, app: Transfers, result: ThreadImported) -> None:
        app.events.publish(core_events.ThreadRowStateChanged(frozenset((result.thread,))))
        app.notify(f"Imported @{result.thread} ({result.imported_messages} messages) as a stopped thread",
                   title="Thread Import")


class Transfers(ThemedApp[TerminalOutcome]):
    """The application supplies transfers through its existing native lifetime."""

    coordination_access: CoordinationAccess
    preparation: PreparationRuntime
    events: core_events.CoreEventStream

    def open_transfer(self, kind: type[Transfer]) -> None:
        access = self.coordination_access
        selected = access.selected(access.observation.observed().service.root)
        self.push_screen(kind.dialog(selected), callback=partial(self.transfer_submitted, selected))

    @boundary_decoder
    def transfer_submitted(self, selected: RouteSelection, request: Transfer | None) -> None:
        """Native Screen.dismiss supplies None on cancel; that absence stops here."""
        if request is not None:
            self.run_worker(request.execute(self, selected),
                            group=type(request).declared_name, exclusive=True)


class TransferDialog(DismissibleScreen[Transfer]):
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

    @staticmethod
    @boundary_decoder
    def require_selection[Value](control: Select[Value]) -> Value:
        """Admit the native optional value once, without a wire encode/decode."""
        value = control.selection
        if value is None:
            raise ValueError("Choose an option.")
        return value


class WireExportProgressView(CancellableWireExport, TransferProgress, WidgetView, ToadNode, Vertical):
    """The export's cancellation capability and a view of its own byte/message counters."""

    layer_name = "wire-export-progress"
    position = "absolute"
    overlay = "screen"
    width = Scalar.from_number(64)
    max_width = Scalar(95, Unit.PERCENT, Unit.WIDTH)
    padding = Spacing(1, 2, 1, 2)

    @property
    def border(self) -> Edges:
        return Edges(*(("solid", self.app.colours.colour(PrimaryColour)),) * 4)

    @property
    def paint_background(self) -> Color:
        return self.app.colours.colour(SurfaceColour)

    @property
    def paint_foreground(self) -> Color:
        return self.app.colours.colour(ForegroundColour)

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


class ExportFormatInput(DeclaredFamily, affix="FormatInput"):
    """UI labels and default filenames, not another wire-format identity."""

    label: ClassVar[str]
    suffix: ClassVar[str]

    @classmethod
    def destination(cls, stem: Path) -> Path:
        return stem.with_suffix(cls.suffix)

    @classmethod
    @abstractmethod
    def format(cls) -> WireExportFormat: ...


class JsonlFormatInput(ExportFormatInput):
    label = "JSON Lines (portable wire)"
    suffix = ".jsonl"

    @classmethod
    def format(cls) -> JsonlFormat:
        return JsonlFormat()


class TextFormatInput(ExportFormatInput):
    label = "Readable text"
    suffix = ".txt"

    @classmethod
    def format(cls) -> TextFormat:
        return TextFormat()


class ExportScopeInput(DeclaredFamily, affix="ScopeInput"):
    """The dialog's human input grammar; Core still resolves the wire scope."""

    label: ClassVar[str]

    @classmethod
    @abstractmethod
    def parse(cls, target: str) -> WireExportScope: ...


class EverythingScopeInput(ExportScopeInput):
    label = "Everything"

    @classmethod
    def parse(cls, target: str) -> EverythingScope:
        return EverythingScope()


class ChannelScopeInput(ExportScopeInput):
    label = "One channel"

    @classmethod
    def parse(cls, target: str) -> ChannelScope:
        return ChannelScope(target)


class DmScopeInput(ExportScopeInput):
    label = "One DM"

    @classmethod
    def parse(cls, target: str) -> DmScope:
        first, second = (name.strip().removeprefix("@") for name in target.split(","))
        return DmScope((first, second))


class WireExportDialog(TransferDialog):
    """Select destination, representation, scope and an explicit size ceiling."""

    default_format: ClassVar[type[ExportFormatInput]] = JsonlFormatInput
    default_scope: ClassVar[type[ExportScopeInput]] = EverythingScopeInput

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.destination_stem = root / "exports" / f"wire-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}"

    @cached_property
    def destination_input(self) -> Input:
        return Input(str(self.default_format.destination(self.destination_stem)),
                     id="export-path", placeholder="Destination path")

    @cached_property
    def format_select(self) -> Select[type[ExportFormatInput]]:
        return Select(
            [(choice.label, choice) for choice in ExportFormatInput.members_with(ExportFormatInput)],
            value=self.default_format, id="export-format", allow_blank=False,
        )

    @cached_property
    def scope_select(self) -> Select[type[ExportScopeInput]]:
        return Select(
            [(choice.label, choice) for choice in ExportScopeInput.members_with(ExportScopeInput)],
            value=self.default_scope, id="export-scope", allow_blank=False,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="transfer-box"):
            yield Static("Export wire history (not a Pi session)")
            yield self.destination_input
            yield self.format_select
            yield self.scope_select
            yield Input(id="export-target", placeholder="#channel or first,second (for DM)")
            yield Input("5242880", id="export-limit", placeholder="Max bytes; empty = full")
            yield Static("", id="transfer-error")
            yield Button("Export", id="submit-transfer")
            yield Button("Cancel", id="cancel-transfer", action=f"screen.{DismissAction.binding_name()}")

    def on_mount(self) -> None:
        self.destination_input.focus()

    @on(Select.Changed, "#export-format")
    def on_format_changed(self, event: Select.Changed) -> None:
        defaults = (str(choice.destination(self.destination_stem))
                    for choice in ExportFormatInput.members_with(ExportFormatInput))
        if self.destination_input.value in defaults:
            chosen = self.require_selection(self.format_select)
            self.destination_input.value = str(chosen.destination(self.destination_stem))

    @on(Button.Pressed, "#submit-transfer")
    def action_submit(self) -> None:
        try:
            path = self.destination_input.value.strip()
            if not path:
                raise ValueError("Choose an output path.")
            target = self.query_one("#export-target", Input).value.strip()
            scope = self.require_selection(self.scope_select).parse(target)
            value = self.query_one("#export-limit", Input).value.strip()
            limit = MaxBytesLimit(int(value)) if value else FullLimit()
            request = WireExportRequest(
                Path(path).expanduser(), self.require_selection(self.format_select).format(), scope, limit,
            )
        except (TypeError, ValueError) as error:
            self._error(str(error))
            return
        self.dismiss(request)


class ThreadImportDialog(TransferDialog):
    """Create one stopped, resumable thread from OpenCode or Codex history."""

    @cached_property
    def harness_select(self) -> Select[type[Harness]]:
        harnesses = Harness.members_with(Harness)
        return Select(
            [(harness.declared_name, harness) for harness in harnesses],
            value=harnesses[0], id="import-harness", allow_blank=False,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="transfer-box"):
            yield Static("Thread Import: a stored harness session")
            yield self.harness_select
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
            self.require_selection(self.harness_select),
            name,
            FieldCodec.decode(ExpectedSession, self.query_one("#import-session-id", Input).value.strip() or None),
            FieldCodec.decode(ImportDirectory, self.query_one("#import-worktree", Input).value.strip() or None),
        ))
