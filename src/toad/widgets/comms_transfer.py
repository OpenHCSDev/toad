"""Inputs for the existing agent-comms export and thread-import operations."""

from __future__ import annotations
from toad.core import events as core_events

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, ClassVar
import asyncio
from functools import partial
from abc import ABC, abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from agent_comms.route_selection import RouteSelection

from agent_comms.exporting import (
    ChannelScope,
    DmScope,
    EverythingScope,
    FullLimit,
    JsonlFormat,
    MaxBytesLimit,
    SelectableWireExportFormat,
    WireExportFormat,
    WireExportLimit,
    WireExportScope,
)
from agent_comms.importing import ImportFormat
from objectstate import ObjectState
from python_introspect import AnnotationChoices, FieldLabel, RegisteredClassChoices
from textual.app import ComposeResult
from textual.binding import CallBinding
from textual.containers import HorizontalGroup, Vertical
from textual.css._style_properties import Edges
from textual.css.scalar import Scalar, Unit
from textual.geometry import Spacing
from textual.widgets import Button, Static
from ui_theme.scheme import ErrorColour, PrimaryColour, SurfaceColour

from toad.forms.field_path import FieldPath
from toad.forms.form_view import InlineFormView
from toad.forms.presentation import FormModal, FormPart
from toad.forms.kinds import Placeholder
from toad.screens.modal import ModalScreen
from toad.setting_choices import Choice, FamilyChoices


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
                                group=FieldCodec.encode(type(request)), exclusive=True)

    async def execute(self, selected: RouteSelection, request: TransferRequest) -> None:
        try:
            comms = self.app.coordination_access.require(selected)
            receipt = await asyncio.to_thread(self.app.coordination_access.write, selected, request.apply, comms)
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title=request.failure_title, severity="error")
        else:
            request.completed(self.app, receipt)


class ExportScopeInput(Choice, DeclaredFamily, affix="ExportScopeInput"):
    """Decode the target text offered by each interactive scope choice."""

    @classmethod
    @abstractmethod
    def read(cls, target: str) -> WireExportScope: ...


class EverythingExportScopeInput(ExportScopeInput):
    title = "Everything"

    @classmethod
    def read(cls, target: str) -> WireExportScope:
        return EverythingScope()


class ChannelExportScopeInput(ExportScopeInput):
    title = "One channel"

    @classmethod
    def read(cls, target: str) -> WireExportScope:
        return ChannelScope(target.strip())


class DmExportScopeInput(ExportScopeInput):
    title = "One DM"

    @classmethod
    def read(cls, target: str) -> WireExportScope:
        return DmScope(tuple(name.strip().removeprefix("@") for name in target.split(",")))


class ImportFormatChoices(AnnotationChoices):
    def choices(self) -> tuple[ImportFormat, ...]:
        return tuple(ImportFormat)


class TransferPanel(FormPart, Vertical):
    width = Scalar.from_number(72)
    max_width = Scalar(95, Unit.PERCENT, Unit.WIDTH)
    max_height = Scalar(95, Unit.VIEW_HEIGHT, Unit.HEIGHT)
    padding = Spacing(1, 2, 1, 2)

    @property
    def border(self) -> Edges:
        return Edges(*(("solid", self.app.colours.colour(PrimaryColour)),) * 4)

    @property
    def paint_background(self):
        return self.app.colours.colour(SurfaceColour)


class TransferForm(InlineFormView):
    max_height = Scalar(60, Unit.VIEW_HEIGHT, Unit.HEIGHT)


class TransferError(FormPart, Static):
    @property
    def paint_foreground(self):
        return self.app.colours.colour(ErrorColour)


class TransferActions(FormPart, HorizontalGroup):
    """The shared native form geometry composes with the horizontal layout."""


class TransferDialog(FormModal, ModalScreen):
    """A declared form owns its edits; this screen owns layout and submission."""

    heading: ClassVar[str]
    submit_label: ClassVar[str]

    class Fields(ABC):
        @abstractmethod
        def request(self) -> TransferRequest: ...

    def __init__(self, fields: Fields, *, focus: FieldPath) -> None:
        super().__init__()
        self.state = ObjectState(fields)
        self.form = TransferForm(self.state, focus=focus.bind(self.state).path)
        self.error = TransferError("", markup=False)
        self.submit_button = Button(self.submit_label)
        self.cancel_button = Button("Cancel")
        self.submit_button.listen(Button.Pressed, self.submitted)
        self.cancel_button.listen(Button.Pressed, self.cancelled)
        self.panel = TransferPanel()

    def compose(self) -> ComposeResult:
        with self.panel:
            yield Static(self.heading)
            yield self.form
            yield self.error
            with TransferActions():
                yield self.submit_button
                yield self.cancel_button

    def on_mount(self) -> None:
        self.state.on_resolved_changed(self.fields_changed)

    def on_unmount(self) -> None:
        self.state.off_resolved_changed(self.fields_changed)

    def fields_changed(self, paths: set[str]) -> None:
        """A dialog may derive another field's default from a changed choice."""

    def cancelled(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_cancel()

    def submitted(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        try:
            self.form.finish()
            request = self.state.to_resolved_object().request()
        except (TypeError, ValueError) as error:
            self.error.update(str(error))
            return
        self.dismiss(request)

    BINDINGS = [CallBinding("escape", action_cancel, "Cancel")]


class WireExportDialog(TransferDialog):
    """Select destination, representation, scope and an explicit size ceiling."""

    heading = "Export wire history (not a Pi session)"
    submit_label = "Export"

    @dataclass(frozen=True)
    class Fields(TransferDialog.Fields):
        destination: Annotated[str, FieldLabel("Destination path")]
        format: Annotated[type[WireExportFormat], RegisteredClassChoices(SelectableWireExportFormat)] = JsonlFormat
        scope: Annotated[type[ExportScopeInput], FamilyChoices(ExportScopeInput)] = EverythingExportScopeInput
        target: Annotated[str, FieldLabel("Scope target"), Placeholder("#channel or first,second (for DM)")] = ""
        max_bytes: Annotated[str, FieldLabel("Max bytes (empty = full)")] = "5242880"

        def request(self) -> WireExportRequest:
            path = self.destination.strip()
            if not path:
                raise ValueError("Choose an output path.")
            ceiling = self.max_bytes.strip()
            return WireExportRequest(
                Path(path).expanduser(), self.format(), self.scope.read(self.target),
                MaxBytesLimit(int(ceiling)) if ceiling else FullLimit(),
            )

    def __init__(self, root: Path) -> None:
        self.default_path = root / "exports" / f"wire-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.jsonl"
        paths = FieldPath(self.Fields)
        super().__init__(self.Fields(str(self.default_path)), focus=paths.destination)
        self.destination_field = paths.destination.bind(self.state)
        self.format_field = paths.format.bind(self.state)

    def fields_changed(self, paths: set[str]) -> None:
        if self.format_field.path.value in paths:
            defaults = {
                str(self.default_path.with_suffix(f".{kind.declared_name}"))
                for kind in SelectableWireExportFormat.members_with(SelectableWireExportFormat)
            }
            if self.destination_field.value in defaults:
                self.destination_field.edit(str(self.default_path.with_suffix(
                    f".{self.format_field.value.declared_name}"
                )))


class ThreadImportDialog(TransferDialog):
    """Create one stopped, resumable thread from OpenCode or Codex history."""

    heading = "Thread Import: OpenCode export/database or Codex rollout"
    submit_label = "Import stopped thread"

    @dataclass(frozen=True)
    class Fields(TransferDialog.Fields):
        format: Annotated[ImportFormat, ImportFormatChoices()] = ImportFormat.OPENCODE
        source: Annotated[str, Placeholder("Source JSON, database or rollout JSONL")] = ""
        name: Annotated[str, FieldLabel("New thread name")] = ""
        session_id: Annotated[str, FieldLabel("Session ID (OpenCode database only)")] = ""
        worktree: Annotated[str, FieldLabel("Project directory override (optional)")] = ""

        def request(self) -> ThreadImportRequest:
            source, name = self.source.strip(), self.name.strip()
            if not source or not name:
                raise ValueError("A source and a new thread name are required.")
            return ThreadImportRequest(
                Path(source).expanduser(), self.format, name,
                self.session_id.strip() or None, self.worktree.strip() or None,
            )

    def __init__(self) -> None:
        super().__init__(self.Fields(), focus=FieldPath(self.Fields).source)
