"""Qt's keymap browser — a thin renderer over `KeymapBrowserState`.

Opened by `QtToadApp.open_keymap_browser` (overrides the `ClientApplication`
stub); the hamburger menu's `KeymapAction` fires that capability. Both
frontends consume the same `toad.client.keymap_browser.KeymapBrowserState`;
Qt owns the widget layout + event routing, nothing else.
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

from toad.client.keymap_browser import KeymapBrowserState, KeymapSelection
from toad.keymap import KeyInvocationId

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


class QtKeymapScreen(QDialog):
    """Modal keymap browser. Lays out:
      - heading + search field + focus-filter checkbox
      - table (rows = actions, columns = Action + one per mode)
      - summary label
      - keys line edit + Apply/Reset/Close buttons
      - status label

    Event routing: every mutation (search text, focus checkbox, cell click,
    Apply, Reset) forwards to `self.state`; afterwards the table re-reads
    `self.state.rows()` and status shows `result.status_text()` /
    `result.should_repopulate()` — polymorphic, no isinstance on result types."""

    def __init__(self, app: "QtToadApp", focused: frozenset[KeyInvocationId]) -> None:
        super().__init__(app)
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.setWindowTitle("Keyboard shortcuts")
        self.app = app
        self.state = KeymapBrowserState(app, focused)
        self._selection: KeymapSelection | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Keyboard shortcuts — tap a mode cell to change its keys"))

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search actions")
        self.search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search)

        self.focus_filter = QCheckBox("Only commands in the previous focus", self)
        self.focus_filter.setChecked(True)
        self.focus_filter.toggled.connect(self._on_focus_toggled)
        layout.addWidget(self.focus_filter)

        self.table = QTableWidget(self)
        self.table.setColumnCount(1 + len(self.state.modes))
        self.table.setHorizontalHeaderLabels(("Action",) + self.state.mode_labels())
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("", self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        controls = QHBoxLayout()
        self.keys = QLineEdit(self)
        self.keys.setPlaceholderText("Keys separated by commas")
        controls.addWidget(self.keys, 1)
        self.apply_button = QPushButton("Apply", self)
        self.apply_button.clicked.connect(self._on_apply_clicked)
        controls.addWidget(self.apply_button)
        self.reset_button = QPushButton("Reset", self)
        self.reset_button.clicked.connect(self._on_reset_clicked)
        controls.addWidget(self.reset_button)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.resize(600, 500)
        self._populate()

    # ---- state → table ----

    def _populate(self) -> None:
        # Pull the two dimmed/warning foreground colors from the shared scheme
        # (MutedColour for the "dim" row, ErrorColour for a key-conflict cell)
        # rather than hand-rolled greys. Same ColourScheme that drives
        # `QtJumpBar`'s styling and `activity.py`'s sweep gradient.
        scheme = self.app.renderer.scheme
        dim_brush = QBrush(QColor(MutedColour.rgb(scheme).hex))
        conflict_brush = QBrush(QColor(ErrorColour.rgb(scheme).hex))
        rows = self.state.rows()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            title_item = QTableWidgetItem(row.title)
            title_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if row.dim:
                title_item.setForeground(dim_brush)
            self.table.setItem(row_index, 0, title_item)
            for column_index, cell in enumerate(row.cells, start=1):
                item = QTableWidgetItem(cell.keys)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if cell.conflict:
                    item.setForeground(conflict_brush)
                self.table.setItem(row_index, column_index, item)

    # ---- event handlers ----

    def _on_search_changed(self, text: str) -> None:
        self.state.set_search(text)
        self._populate()

    def _on_focus_toggled(self, on: bool) -> None:
        self.state.set_focus_filter(on)
        self._populate()

    def _on_cell_clicked(self, row: int, column: int) -> None:
        selection = self.state.select(row, column)
        self._selection = selection
        if selection is None:
            self.summary.setText("")
            self.status.setText("")
            self.keys.setText("")
            return
        self.keys.setText(self.state.current_keys(selection))
        self.summary.setText(self.state.summary(selection))
        self.status.setText("; ".join(self.state.conflicts(selection)))
        self.keys.setFocus()

    def _on_apply_clicked(self) -> None:
        if self._selection is None:
            self.status.setText("Select a mode cell first")
            return
        self.app.run_operation(_KeymapSave, self._apply_async)

    def _on_reset_clicked(self) -> None:
        if self._selection is None:
            self.status.setText("Select a mode cell first")
            return
        self.app.run_operation(_KeymapSave, self._reset_async)

    async def _apply_async(self) -> None:
        assert self._selection is not None
        result = await self.state.apply_keys(self._selection, self.keys.text())
        self._show_result(result)

    async def _reset_async(self) -> None:
        assert self._selection is not None
        result = await self.state.reset_keys(self._selection)
        self._show_result(result)

    def _show_result(self, result) -> None:
        if result.should_repopulate():
            self._populate()
        self.status.setText(result.status_text())


class _KeymapSave:
    """Operation marker for `run_operation` — lets the app track concurrent
    keymap saves the same way it tracks other coalesced operations."""
