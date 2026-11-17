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
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from toad.client.menu_entry import MenuEntry
from toad.qt.metrics import UiGap


class QtMenuRow(QWidget):
    """One menu row: a bold key-display column on the left and a label/description
    column that fills the rest. A click fires the entry's action. The whole row is
    the clickable target, not just the text, so a fat-fingered tap on the phone still
    counts as a selection."""

    def __init__(self, entry: MenuEntry, chosen: Callable[[MenuEntry], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._entry = entry
        self._chosen = chosen
        self._button = QPushButton(self)
        self._button.setFlat(True)
        self._button.setMinimumHeight(44)
        self._button.clicked.connect(self._fire)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._button)
        # The button is the hit target; the two labels paint over it inside an
        # inner layout so the row reads as [bold key] [label] without the button's
        # own text getting in the way.
        inner = QHBoxLayout(self._button)
        inner.setContentsMargins(UiGap.dialog, UiGap.tight, UiGap.dialog, UiGap.tight)
        inner.setSpacing(UiGap.dialog)
        key = QLabel(entry.key_display, self._button)
        key.setStyleSheet("font-weight: bold;")
        key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        inner.addWidget(key)
        text = entry.label if not entry.description else f"{entry.label} — {entry.description}"
        label = QLabel(text, self._button)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        inner.addWidget(label, 1)

    def _fire(self) -> None:
        self._chosen(self._entry)


class QtMenu(QFrame):
    """A column of MenuEntry rows. The container itself is a QFrame (not a top-level
    window — important on Qt-for-Android where every QWindow needs its own EGL surface
    and a floating menu would deadlock the compositor). Its visibility is managed by
    whatever opened it (hamburger button, long-press handler). `show_entries()` swaps
    the current entry list in place and shows the menu; `hide()` is inherited."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
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
            self._layout.addWidget(QtMenuRow(entry, self._chose, parent=self))
        self.show()

    def _chose(self, entry: MenuEntry) -> None:
        self.hide()
        entry.run()
