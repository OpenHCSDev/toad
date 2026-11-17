"""Qt's transfer dialogs — the frontend half of `toad.client.transfers`.

Opened by `QtToadApp.open_transfer(kind)` (which overrides the `ClientApplication`
stub); the hamburger menu's `TransferMenuAction` fires that capability once per
declared `Transfer` member. Both frontends share `toad.client.transfers.Transfer`
+ `TransferRequest`; Textual's per-kind dialogs live in
`toad.widgets.comms_transfer`, Qt's live here. The submit path builds the typed
request from field values and routes back through `QtToadApp.start_transfer_task`
so one running task per kind supersedes repeat submissions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from agent_comms.importing import ThreadImported
from agent_comms.installer.harness_install import Harness
from agent_comms.messaging.exporting import (
    FullLimit,
    MaxBytesLimit,
    WireExportProvenance,
)
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.registry.thread_management import ImportDirectory
from agent_comms.registry.thread_text import ExpectedSession
from ui_theme.scheme import ErrorColour

from toad.client.transfers import Transfer, TransferHost
from toad.qt.metrics import UiGap
from toad.widgets.comms_transfer import (
    ExportFormatInput,
    ExportScopeInput,
    ThreadImportRequest,
    WireExportRequest,
)

if TYPE_CHECKING:
    from toad.client.connection import CapturedSource


class QtTransferDialog(QDialog):
    """Shared frame for Qt transfer dialogs: heading on top, a form (QFormLayout)
    of field widgets, an inline error line, and OK/Cancel buttons. Subclasses
    override `_build_form()` to populate fields and `_compose()` to assemble the
    typed request from them. Submits route back through the host via
    `host.start_transfer_task(request, selected)`."""

    heading: ClassVar[str]
    submit_label: ClassVar[str]
    kind: ClassVar[type[Transfer]]

    def __init__(self, host: TransferHost, selected: CapturedSource,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self._selected = selected
        self.setWindowTitle(self.heading)
        self.setModal(True)
        self.resize(560, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.normal)

        header = QLabel(self.heading)
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        self._form = QFormLayout()
        self._form.setSpacing(UiGap.normal)
        self._build_form(self._form)
        layout.addLayout(self._form)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        # ErrorColour is a scheme role; the actual hex comes from the host's
        # colour scheme — read at build time so dialog theme matches the rest.
        scheme = getattr(host, "renderer", None)
        if scheme is not None and hasattr(scheme, "scheme"):
            self._error.setStyleSheet(f"color: {ErrorColour.rgb(scheme.scheme).hex};")
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText(self.submit_label)
        ok_button.setDefault(True)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_form(self, form: QFormLayout) -> None:
        """Subclasses add fields via `form.addRow(label, widget)`."""
        raise NotImplementedError

    def _compose(self) -> Transfer:
        """Build and return the typed request from field values. Raise ValueError
        on invalid input; the message is shown in the dialog's error line."""
        raise NotImplementedError

    def _on_accept(self) -> None:
        try:
            request = self._compose()
        except (TypeError, ValueError) as error:
            self._error.setText(str(error) or "Invalid input.")
            return
        self._host.start_transfer_task(request, self._selected)
        self.accept()


class QtWireExportDialog(QtTransferDialog):
    """Export wire history — destination, format, scope, optional per-target
    narrowing, byte ceiling. Mirrors Textual's `WireExportDialog` fields."""

    heading = "Export wire history"
    submit_label = "Export"
    kind = WireExportRequest

    def __init__(self, host: TransferHost, selected: CapturedSource,
                 parent: QWidget | None = None) -> None:
        self._destination_stem = (
            selected.root / "exports"
            / f"wire-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}"
        )
        super().__init__(host, selected, parent)

    def _build_form(self, form: QFormLayout) -> None:
        self._format = QComboBox()
        for choice in ExportFormatInput.members_with(ExportFormatInput):
            self._format.addItem(choice.label, choice)
        self._format.currentIndexChanged.connect(self._format_changed)

        self._destination = QLineEdit()
        self._destination.setPlaceholderText("Destination path")
        self._destination.setText(
            str(self._current_format().destination(self._destination_stem)),
        )

        self._scope = QComboBox()
        for choice in ExportScopeInput.members_with(ExportScopeInput):
            self._scope.addItem(choice.label, choice)

        self._target = QLineEdit()
        self._target.setPlaceholderText("#channel or first,second (for DM)")

        self._limit = QLineEdit()
        self._limit.setText("5242880")
        self._limit.setPlaceholderText("Max bytes; empty = full")

        form.addRow("Destination:", self._destination)
        form.addRow("Format:", self._format)
        form.addRow("Scope:", self._scope)
        form.addRow("Target:", self._target)
        form.addRow("Byte limit:", self._limit)

    def _current_format(self) -> type[ExportFormatInput]:
        return self._format.currentData()

    def _current_scope(self) -> type[ExportScopeInput]:
        return self._scope.currentData()

    def _format_changed(self, _index: int) -> None:
        """Mirror Textual's `WireExportDialog.format_changed`: when the user
        hasn't typed over the default destination, swap it to the new format's
        default so the extension matches the chosen format."""
        defaults = {
            str(choice.destination(self._destination_stem))
            for choice in ExportFormatInput.members_with(ExportFormatInput)
        }
        if self._destination.text() in defaults:
            self._destination.setText(
                str(self._current_format().destination(self._destination_stem)),
            )

    def _compose(self) -> WireExportRequest:
        path = self._destination.text().strip()
        if not path:
            raise ValueError("Choose an output path.")
        target = self._target.text().strip()
        scope = self._current_scope().parse(target)
        limit_text = self._limit.text().strip()
        limit = MaxBytesLimit(int(limit_text)) if limit_text else FullLimit()
        return WireExportRequest(
            Path(path).expanduser(),
            self._current_format().format(),
            scope,
            limit,
        )


class QtThreadImportDialog(QtTransferDialog):
    """Import a stopped, resumable thread from a harness session (OpenCode,
    Codex, Pi, Claude Code). Mirrors Textual's `ThreadImportDialog` fields."""

    heading = "Thread Import — stored harness session"
    submit_label = "Import stopped thread"
    kind = ThreadImportRequest

    def _build_form(self, form: QFormLayout) -> None:
        self._harness = QComboBox()
        for harness in Harness.members_with(Harness):
            self._harness.addItem(harness.declared_name, harness)

        self._source = QLineEdit()
        self._source.setPlaceholderText("Source JSON, database or rollout JSONL")

        self._name = QLineEdit()
        self._name.setPlaceholderText("New thread name")

        self._session = QLineEdit()
        self._session.setPlaceholderText("Session ID (OpenCode database only)")

        self._worktree = QLineEdit()
        self._worktree.setPlaceholderText("Project directory override (optional)")

        form.addRow("Harness:", self._harness)
        form.addRow("Source:", self._source)
        form.addRow("New name:", self._name)
        form.addRow("Session ID:", self._session)
        form.addRow("Worktree:", self._worktree)

    def _compose(self) -> ThreadImportRequest:
        source = self._source.text().strip()
        name = self._name.text().strip()
        if not source or not name:
            raise ValueError("A source and a new thread name are required.")
        return ThreadImportRequest(
            Path(source).expanduser(),
            self._harness.currentData(),
            name,
            FieldCodec.decode(ExpectedSession, self._session.text().strip() or None),
            FieldCodec.decode(ImportDirectory, self._worktree.text().strip() or None),
        )


# Per-kind Qt dialog registry: Transfer family grows by declaration, and so do
# these. Keeping the registry close to the dialog classes (built via
# QtTransferDialog.__init_subclass__ registration) keeps the mapping declarative
# instead of a hand-maintained table.
_QT_DIALOGS: dict[type[Transfer], type[QtTransferDialog]] = {
    WireExportRequest: QtWireExportDialog,
    ThreadImportRequest: QtThreadImportDialog,
}


def qt_dialog_for(kind: type[Transfer], host: TransferHost,
                  selected: CapturedSource,
                  parent: QWidget | None = None) -> QtTransferDialog:
    """Build the Qt dialog registered for `kind`, raising loudly if no dialog
    is registered — a silent no-op would give the user a dead menu item."""
    try:
        cls = _QT_DIALOGS[kind]
    except KeyError as error:
        raise NotImplementedError(
            f"No Qt dialog registered for transfer kind {kind.declared_name!r}. "
            f"Register one in toad.qt.transfer._QT_DIALOGS.",
        ) from error
    return cls(host, selected, parent)
