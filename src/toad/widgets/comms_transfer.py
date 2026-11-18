"""Inputs for the existing agent-comms export and thread-import operations."""

from abc import abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cached_property, partial
from pathlib import Path
from time import monotonic

from agent_comms.importing import ThreadImported
from agent_comms.installer.harness_install import Harness
from agent_comms.messaging.exporting import (
    WireExportFormat,
    WireExportLimit,
    WireExportProvenance,
    WireExportScope,
)
from agent_comms.nominal.field_codec import boundary_decoder
from agent_comms.registry.thread_management import ImportDirectory
from agent_comms.registry.thread_text import ExpectedSession
from agent_comms.transport.progress import (
    CancellableWireExport,
    WireExportCancelled,
    WireExportProgress,
)
from agent_comms.transport.tools.sidebar import (
    CommsExportWireTool,
    CommsImportThreadTool,
)
from textual import on
from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Vertical, VerticalGroup, VerticalScroll
from textual.css._style_properties import Edges
from textual.css.native import Keyword, NativeDeclaration, Percent, Variable
from textual.css.scalar import Scalar, Unit
from textual.css.styles import Styles
from textual.events import Mount, Unmount
from textual.geometry import Spacing
from textual.message import Message
from textual.view import FILL, WidgetView
from textual.widgets import Input, Select, Static
from toad.application_outcome import ApplicationOutcome
from toad.comms_host import CommsHost
from ui_theme.scheme import (
    BackgroundColour,
    ErrorColour,
    ForegroundColour,
    PrimaryColour,
    SurfaceColour,
)

from toad.app_node import ToadNode
from toad.client.connection import CapturedSource, CoordinationAccess, Observing
from toad.client.transfer_forms import (
    ExportFormatInput,
    ExportScopeInput,
    ThreadImportForm,
    TransferForm,
    WireExportForm,
)
from toad.client.transfers import (
    Transfer,
    TransferHost,
    TransferProgress,
    TransferRequest,
)
from toad.core import events as core_events
from toad.native_style import (
    CenteredChildren,
    DockedBottom,
    FillWidth,
    SurfaceBackground,
)
from toad.screens.modal import DismissibleScreen
from toad.widgets.acting_button import (
    ActingButton,
    ConfirmButton,
    Confirms,
    DismissButton,
)


# `Transfer`, `TransferRequest`, `TransferProgress` and `TransferHost` are declared in
# `toad.client.transfers`, the forms in `toad.client.transfer_forms`. Each frontend finds a
# kind's dialog with `TransferForm.for_kind` over its own dialog family.


@dataclass(frozen=True)
class WireExportRequest(TransferRequest[WireExportProvenance]):
    destination: Path
    format: WireExportFormat
    scope: WireExportScope
    limit: WireExportLimit

    failure_title = "Wire export failed"
    title = "Export wire history…"
    cancelled_by = (WireExportCancelled,)

    def perform(self, access: CoordinationAccess, selected: CapturedSource,
                observer: TransferProgress) -> WireExportProvenance:
        """Core's host writes the export; its progress and cancel reach this observer."""
        return access.write(selected, access.observing(selected.root).core.call, CommsExportWireTool(
            destination=self.destination, format=self.format, scope=self.scope, limit=self.limit,
        ).observed_by(observer))

    @asynccontextmanager
    async def progress(self, app: App[ApplicationOutcome]) -> AsyncIterator[TransferProgress]:
        progress = WireExportProgressView()
        try:
            await app.mount(progress)
            yield progress
        finally:
            progress.cancel()
            await progress.remove()

    def cancelled(self, app: App[ApplicationOutcome]) -> None:
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

    def perform(self, access: CoordinationAccess, selected: CapturedSource,
                observer: TransferProgress) -> ThreadImported:
        return access.write(selected, access.observing(selected.root).core.call, CommsImportThreadTool(
            source=self.source, harness=self.harness, name=self.name, session=self.session,
            worktree=self.worktree))

    def completed(self, app: Transfers, result: ThreadImported) -> None:
        app.events.publish(core_events.ThreadRowStateChanged(frozenset((result.thread,))))
        app.notify(f"Imported @{result.thread} ({result.imported_messages} messages) as a stopped thread",
                   title="Thread Import")


class Transfers(CommsHost[Observing], TransferHost):
    """Textual's `TransferHost`: a pushed `TransferDialog` returns the composed request
    through dismiss, and `run_worker(..., exclusive=True)` tags the task by the kind's
    declared name so re-opening the same kind supersedes the previous run."""

    def open_transfer(self, kind: type[Transfer]) -> None:
        access = self.coordination_access
        selected = access.selected(access.observation.observed().root)
        self.push_screen(TransferDialog.for_kind(kind)(selected),
                         callback=partial(self.transfer_submitted, selected))

    def start_transfer_task(self, request: Transfer, selected: CapturedSource) -> None:
        self.run_worker(request.execute(self, selected),
                        group=type(request).declared_name, exclusive=True)

    @boundary_decoder
    def transfer_submitted(self, selected: CapturedSource, request: Transfer | None) -> None:
        """Native Screen.dismiss supplies None on cancel; that absence stops here."""
        if request is not None:
            self.start_transfer_task(request, selected)


class TransferPanel(SurfaceBackground, Vertical):
    """One bounded frame; fields may scroll without displacing its actions."""

    native_theme = (NativeDeclaration.of(Styles.border, Keyword("solid"), Variable(PrimaryColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = 72
        self.styles.max_width = Scalar(95, Unit.PERCENT, Unit.WIDTH)
        self.styles.height = FILL
        self.styles.max_height = Scalar(95, Unit.PERCENT, Unit.HEIGHT)
        self.styles.padding = Spacing(1, 2, 1, 2)


class TransferFields(VerticalScroll, can_focus=False):
    """The native scroll viewport retains the actual field widgets and values."""


class TransferActions(DockedBottom, VerticalGroup):
    """Actions retain their vertical order outside the scrolling fields."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = Spacing(1, 0, 0, 0)


class TransferField(FillWidth):
    """One field-spacing declaration shared by native text and choice controls."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = Spacing(0, 0, 1, 0)


class TextField(TransferField, Input):
    """A transfer's text entry, retaining Input's native editing behavior."""


class ChoiceField[Value](TransferField, Select[Value]):
    """A transfer's choice entry, retaining Select's native popup behavior."""


class ExportPath(TextField):
    """Where the export is written."""


class ExportTarget(TextField):
    """The channel or DM peers an export reads."""


class ExportLimit(TextField):
    """The export's byte budget."""


class ImportSource(TextField):
    """The transcript an import reads."""


class ImportName(TextField):
    """The imported thread's new name."""


class ImportSessionId(TextField):
    """The OpenCode session an import selects."""


class ImportWorktree(TextField):
    """The imported thread's project directory."""


class ExportFormatChoice(ChoiceField[type["ExportFormatInput"]]):
    """The export's file format; choosing one moves a default destination with it."""

    @on(Select.Changed)
    def chosen(self, message: Select.Changed) -> None:
        message.stop()
        self.query_ancestor(WireExportDialog).format_changed()


class ExportScopeChoice(ChoiceField[type["ExportScopeInput"]]):
    """What the export reads."""


class ExportProgress(Static):
    """How much the running export has written."""


class TransferError(Static):
    native_theme = (
        NativeDeclaration.of(Styles.color, Variable(ErrorColour.name)),
    )


class TransferDialog(TransferForm, Confirms, CenteredChildren, DismissibleScreen[Transfer]):
    """Both transfer grammars share their frame, viewport and native dismissal."""

    native_theme = (
        NativeDeclaration.of(Styles.background, Variable(BackgroundColour.name), Percent(40)),
    )

    def __init__(self, selected: CapturedSource) -> None:
        super().__init__()
        self.begin(selected)


    def compose(self) -> ComposeResult:
        with TransferPanel():
            yield Static(self.heading)
            with TransferFields():
                yield from self.fields()
            yield TransferError("")
            with TransferActions():
                yield ConfirmButton(self.submit_label)
                yield DismissButton("Cancel")

    @abstractmethod
    def fields(self) -> ComposeResult: ...

    def show_error(self, text: str) -> None:
        self.query_one(TransferError).update(text)

    def submit(self, request: Transfer) -> None:
        self.dismiss(request)

    async def confirm(self) -> None:
        self.confirm_request()

    @staticmethod
    @boundary_decoder
    def require_selection[Value](control: Select[Value]) -> Value:
        """Admit the native optional value once, without a wire encode/decode."""
        value = control.selection
        if value is None:
            raise ValueError("Choose an option.")
        return value


class CancelExportButton(ActingButton):
    """Stops the running export."""

    async def act(self) -> None:
        self.query_ancestor(WireExportProgressView).cancel_export()


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
        yield ExportProgress("0 messages · 0 bytes written")
        yield CancelExportButton("Cancel export")

    def advanced(self, progress: WireExportProgress) -> None:
        now = monotonic()
        if now - self.last_report >= 0.1:
            self.last_report = now
            self.post_message(self.Updated(progress))

    @on(Updated)
    def update_progress(self, event: Updated) -> None:
        progress = event.progress
        self.query_one(ExportProgress).update(
            f"{progress.messages_written:,} messages · {progress.bytes_written:,} bytes written")

    def cancel_export(self) -> None:
        self.cancel()
        button = self.query_one(CancelExportButton)
        button.label = "Cancelling…"
        button.disabled = True

    @on(Unmount)
    def on_unmount(self) -> None:
        self.cancel()


class WireExportDialog(WireExportForm, TransferDialog):
    request_kind = WireExportRequest

    @cached_property
    def destination_input(self) -> Input:
        return ExportPath(self.default_destination, placeholder=self.destination_placeholder)

    @cached_property
    def format_select(self) -> Select[type[ExportFormatInput]]:
        return ExportFormatChoice(list(self.format_options()), value=self.default_format, allow_blank=False)

    @cached_property
    def scope_select(self) -> Select[type[ExportScopeInput]]:
        return ExportScopeChoice(list(self.scope_options()), value=self.default_scope, allow_blank=False)

    def fields(self) -> ComposeResult:
        yield self.destination_input
        yield self.format_select
        yield self.scope_select
        yield ExportTarget(placeholder=self.target_placeholder)
        yield ExportLimit(self.limit_default, placeholder=self.limit_placeholder)

    @on(Mount)
    def on_mount(self) -> None:
        self.destination_input.focus()

    def format_changed(self) -> None:
        self.destination_input.value = self.destination_for_format(
            self.destination_input.value, self.require_selection(self.format_select))

    def destination_text(self) -> str:
        return self.destination_input.value

    def target_text(self) -> str:
        return self.query_one(ExportTarget).value

    def limit_text(self) -> str:
        return self.query_one(ExportLimit).value

    def chosen_format(self) -> type[ExportFormatInput]:
        return self.require_selection(self.format_select)

    def chosen_scope(self) -> type[ExportScopeInput]:
        return self.require_selection(self.scope_select)


class ThreadImportDialog(ThreadImportForm, TransferDialog):
    request_kind = ThreadImportRequest

    @cached_property
    def harness_select(self) -> Select[type[Harness]]:
        options = list(self.harness_options())
        return ChoiceField(options, value=options[0][1], allow_blank=False)

    def fields(self) -> ComposeResult:
        yield self.harness_select
        yield ImportSource(placeholder=self.source_placeholder)
        yield ImportName(placeholder=self.name_placeholder)
        yield ImportSessionId(placeholder=self.session_placeholder)
        yield ImportWorktree(placeholder=self.worktree_placeholder)

    @on(Mount)
    def on_mount(self) -> None:
        self.query_one(ImportSource).focus()

    def source_text(self) -> str:
        return self.query_one(ImportSource).value

    def name_text(self) -> str:
        return self.query_one(ImportName).value

    def session_text(self) -> str:
        return self.query_one(ImportSessionId).value

    def worktree_text(self) -> str:
        return self.query_one(ImportWorktree).value

    def chosen_harness(self) -> type[Harness]:
        return self.require_selection(self.harness_select)
