"""Qt's keymap browser: the shared `KeymapBrowsing` flow drawn in Qt.

Opened by `QtToadApp.open_keymap_browser`. The words, the filter, what a selected cell
fills in, Apply/Reset and how a result shows are inherited from the flow Textual's
`KeymapScreen` inherits; this module adds only Qt widgets and their reads and writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from ui_theme.scheme import ErrorColour, MutedColour

from toad.client.keymap_browser import KeymapBrowsing
from toad.keymap import KeyInvocationId
from toad.qt.metrics import UiGap

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


class QtKeymapScreen(KeymapBrowsing, QDialog):
    """Modal keymap browser: heading, search, focus filter, the action × mode table,
    the selection's summary, the keys field with Apply/Reset/Close, and a status line."""

    def __init__(self, app: QtToadApp, focused: frozenset[KeyInvocationId]) -> None:
        super().__init__(app)
        self.app = app
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.setWindowTitle("Keyboard shortcuts")
        self.begin_browsing(app, focused)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.loose)
        layout.addWidget(QLabel(self.heading))
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(self.search_placeholder)
        self.search.textChanged.connect(self.refresh_rows)
        layout.addWidget(self.search)
        self.focus_filter = QCheckBox(self.focus_filter_label, self)
        self.focus_filter.setChecked(True)
        self.focus_filter.toggled.connect(self.refresh_rows)
        layout.addWidget(self.focus_filter)

        self.table = QTableWidget(self)
        self.table.setColumnCount(1 + len(self.state.modes))
        self.table.setHorizontalHeaderLabels(("Action",) + self.state.mode_labels())
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self.selection_changed)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("", self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        controls = QHBoxLayout()
        self.keys = QLineEdit(self)
        self.keys.setPlaceholderText(self.keys_placeholder)
        controls.addWidget(self.keys, 1)
        for label, act in (("Apply", self.apply_typed_keys), ("Reset", self.reset_selected_keys)):
            button = QPushButton(label, self)
            button.clicked.connect(lambda _checked=False, act=act: self.app.run_operation(_KeymapSave, act))
            controls.addWidget(button)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        controls.addWidget(close)
        layout.addLayout(controls)
        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.resize(600, 500)
        self.refresh_rows()

    # The native reads and writes `KeymapBrowsing` asks for.

    def selected(self):
        return self.state.select(self.table.currentRow(), self.table.currentColumn())

    def typed_keys(self) -> str:
        return self.keys.text()

    def search_text(self) -> str:
        return self.search.text()

    def focus_filter_on(self) -> bool:
        return self.focus_filter.isChecked()

    def show_rows(self, rows) -> None:
        scheme = self.app.renderer.scheme
        dim = QBrush(QColor(MutedColour.rgb(scheme).hex))
        conflict = QBrush(QColor(ErrorColour.rgb(scheme).hex))
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            title = QTableWidgetItem(row.title)
            title.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if row.dim:
                title.setForeground(dim)
            self.table.setItem(row_index, 0, title)
            for column_index, cell in enumerate(row.cells, start=1):
                item = QTableWidgetItem(cell.keys)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if cell.conflict:
                    item.setForeground(conflict)
                self.table.setItem(row_index, column_index, item)

    def show_selection(self, keys: str, summary: str, conflicts: str) -> None:
        self.keys.setText(keys)
        self.summary.setText(summary)
        self.status.setText(conflicts)

    def show_status(self, text: str) -> None:
        self.status.setText(text)

    def focus_keys(self) -> None:
        self.keys.setFocus()

    def forget_selection(self) -> None:
        self.table.setCurrentCell(-1, -1)


class _KeymapSave:
    """Operation marker for `run_operation`: the app tracks concurrent keymap saves the
    way it tracks its other coalesced operations."""
