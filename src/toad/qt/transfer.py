"""Qt's transfer dialogs: the shared transfer forms (`toad.client.transfer_forms`) drawn in Qt.

Heading, fields, placeholders, defaults, choices and how the answers become the typed
request are inherited from the forms Textual's `TransferDialog`s inherit. This module adds
only Qt widgets, reading them, and how a request leaves: back through
`TransferHost.start_transfer_task`, so one running task per kind supersedes a repeat.
`QtToadApp.open_transfer` finds a kind's dialog with `QtTransferDialog.for_kind`.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

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

from toad.client.transfer_forms import ExportFormatInput, ExportScopeInput, ThreadImportForm, TransferForm, WireExportForm
from toad.client.transfers import Transfer, TransferHost
from toad.qt.metrics import UiGap
from toad.widgets.comms_transfer import ThreadImportRequest, WireExportRequest

if TYPE_CHECKING:
    from agent_comms.installer.harness_install import Harness

    from toad.client.connection import CapturedSource


def _line(text: str = "", placeholder: str = "") -> QLineEdit:
    line = QLineEdit(text)
    line.setPlaceholderText(placeholder)
    return line


def _choices(options) -> QComboBox:
    combo = QComboBox()
    for label, value in options:
        combo.addItem(label, value)
    return combo


class QtTransferDialog(TransferForm, QDialog):
    """The frame every Qt transfer dialog shares: heading, the form's rows, an error
    line, and submit/cancel buttons."""

    def __init__(self, host: TransferHost, selected: CapturedSource, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self.begin(selected)
        self.setWindowTitle(self.heading)
        self.setModal(True)
        self.resize(560, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.normal)
        header = QLabel(self.heading)
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)
        form = QFormLayout()
        form.setSpacing(UiGap.normal)
        for label, widget in self.rows():
            form.addRow(label, widget)
        layout.addLayout(form)
        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: palette(link-visited);")
        layout.addWidget(self._error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(self.submit_label)
        ok.setDefault(True)
        buttons.accepted.connect(self.confirm_request)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @abstractmethod
    def rows(self) -> tuple[tuple[str, QWidget], ...]:
        """The form's fields as label and widget, top to bottom."""

    def show_error(self, text: str) -> None:
        self._error.setText(text)

    def submit(self, request: Transfer) -> None:
        self._host.start_transfer_task(request, self.selected)
        self.accept()


class QtWireExportDialog(WireExportForm, QtTransferDialog):
    request_kind = WireExportRequest

    def rows(self) -> tuple[tuple[str, QWidget], ...]:
        self._destination = _line(self.default_destination, self.destination_placeholder)
        self._format = _choices(self.format_options())
        self._format.setCurrentIndex(self._format.findData(self.default_format))
        self._format.currentIndexChanged.connect(self._format_changed)
        self._scope = _choices(self.scope_options())
        self._scope.setCurrentIndex(self._scope.findData(self.default_scope))
        self._target = _line(placeholder=self.target_placeholder)
        self._limit = _line(self.limit_default, self.limit_placeholder)
        return (("Destination:", self._destination), ("Format:", self._format), ("Scope:", self._scope),
                ("Target:", self._target), ("Byte limit:", self._limit))

    def _format_changed(self, _index: int) -> None:
        self._destination.setText(self.destination_for_format(self._destination.text(), self.chosen_format()))

    def destination_text(self) -> str:
        return self._destination.text()

    def target_text(self) -> str:
        return self._target.text()

    def limit_text(self) -> str:
        return self._limit.text()

    def chosen_format(self) -> type[ExportFormatInput]:
        return self._format.currentData()

    def chosen_scope(self) -> type[ExportScopeInput]:
        return self._scope.currentData()


class QtThreadImportDialog(ThreadImportForm, QtTransferDialog):
    request_kind = ThreadImportRequest

    def rows(self) -> tuple[tuple[str, QWidget], ...]:
        self._harness = _choices(self.harness_options())
        self._source = _line(placeholder=self.source_placeholder)
        self._name = _line(placeholder=self.name_placeholder)
        self._session = _line(placeholder=self.session_placeholder)
        self._worktree = _line(placeholder=self.worktree_placeholder)
        return (("Harness:", self._harness), ("Source:", self._source), ("New name:", self._name),
                ("Session ID:", self._session), ("Worktree:", self._worktree))

    def source_text(self) -> str:
        return self._source.text()

    def name_text(self) -> str:
        return self._name.text()

    def session_text(self) -> str:
        return self._session.text()

    def worktree_text(self) -> str:
        return self._worktree.text()

    def chosen_harness(self) -> type[Harness]:
        return self._harness.currentData()
