"""Qt's structured menu widget: renders a tuple of toolkit-neutral MenuEntry rows as
`[bold key] [label / description]`, matching the Textual `Menu` widget's row structure.

A single widget renders both the application (hamburger) menu and the message-context
(long-press on a row) menu, so the two paths share rendering, layout and click handling,
and the only thing that differs is which MenuEntry tuple each one supplies.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.widgets.fitted_text import ElidedLine

from toad.client.block_menu import BlockMenu
from toad.client.input_modality import InputModality, KeyboardInput, TouchInput
from toad.client.menu_entry import MenuEntry
from toad.qt.metrics import UiGap


def platform_input() -> type[InputModality]:
    """Qt on Android is driven by touch; elsewhere by keys."""
    return TouchInput if QGuiApplication.platformName() == "android" else KeyboardInput


class QtMenuRow(QWidget):
    """One menu row: a bold key column (when the menu's modality shows keys) and a label
    column that fills the rest. Under touch the description is a second line elided to the
    row's width; under keys it follows the label. A click fires the entry's action; the
    whole row is the clickable target, so a fat-fingered tap on the phone still counts.

    The labels are laid over a QPushButton. A QFrame row whose own area was the target, with
    wrapping text (QLabel word wrap, then WrappedText), was tried (2026-11-18): after the
    panel opened over two tabs, qasync's loop ran no callbacks once the window closed, and
    this button row did not. The cause inside the QFrame row is not established."""

    def __init__(self, entry: MenuEntry, menu: QtMenu, chosen: Callable[[MenuEntry], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._entry = entry
        self._chosen = chosen
        self._button = QPushButton(self)
        self._button.setFlat(True)
        self._button.clicked.connect(self._fire)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._button)
        inner = QHBoxLayout(self._button)
        inner.setContentsMargins(UiGap.dialog, UiGap.tight, UiGap.dialog, UiGap.tight)
        inner.setSpacing(UiGap.dialog)
        if keys := menu.row_keys(entry):
            key = QLabel(keys, self._button)
            key.setStyleSheet("font-weight: bold;")
            key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            inner.addWidget(key)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.label = ElidedLine(menu.row_text(entry))
        self.label.setParent(self._button)
        text.addWidget(self.label)
        lines = 1
        if entry.description and not menu.input_modality.describes_inline():
            description = ElidedLine(entry.description)
            description.setParent(self._button)
            description.setEnabled(False)  # the theme's muted text, as a secondary line
            text.addWidget(description)
            lines = 2
        inner.addLayout(text, 1)
        margins = inner.contentsMargins()
        height = lines * self.fontMetrics().lineSpacing() + margins.top() + margins.bottom()
        self._button.setMinimumHeight(max(44, menu.input_modality.row_height, height))

    def _fire(self) -> None:
        self._chosen(self._entry)


class QtMenu(BlockMenu, QFrame):
    """A column of MenuEntry rows. The container itself is a QFrame (not a top-level
    window — important on Qt-for-Android where every QWindow needs its own EGL surface
    and a floating menu would deadlock the compositor). Its visibility is managed by
    whatever opened it (hamburger button, long-press handler). `show_entries()` swaps
    the current entry list in place and shows the menu; `hide()` is inherited."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.input_modality = platform_input()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.normal)
        self._layout.setSpacing(UiGap.tight)
        self.hide()

    def show_entries(self, entries: Iterable[MenuEntry]) -> None:
        """Replace the rows with ``entries`` and show the menu. A selection runs the
        entry's action and dismisses the menu."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for entry in entries:
            self._layout.addWidget(QtMenuRow(entry, self, self._chose, parent=self))
        self.show()

    def _chose(self, entry: MenuEntry) -> None:
        self.hide()
        entry.run()
