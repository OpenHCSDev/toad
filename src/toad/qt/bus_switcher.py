"""Qt bus switcher: the hamburger-triggered picker. Extracts Welcome's existing
bus-listing composition (tree of `BusRow` items + `BusAddress` input) into a
reusable panel so the hamburger "Switch bus" entry shows literally what Welcome
already draws under its Buses section — no second rendering path.

Inherits the shared `BusListing` contract so the rows (held buses merged with
discovered peers via `PickerRow.with_found`), the ask-tailnet-again-on-open
behavior, the prompt text template (`BusSwitcherPrompt`), and PickerRow
dispatch all live in one place. The Qt layer here is layout + show/hide, not
logic.

Inline QFrame child of `QtToadApp` — not a QDialog — same EGL rationale as
`QtMenu`: a top-level popup needs its own EGL surface and deadlocks the
Pixel 8a compositor.

Tailnet answers reach the panel through `QtToadApp.register_bus_listing` /
`deregister_bus_listing`: the panel registers on show, deregisters on hide, so
`tailnet_answered` routes answers to it (and to Welcome, always registered).
"""

from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from toad.client.bus_selection import (
    BusListing,
    BusPickerHost,
    BusSwitcherPrompt,
    PickerRow,
)
from toad.qt.metrics import UiGap
from toad.qt.tap_flash import QtPushButton
from toad.qt.window import (
    BusAddress,
    BusRow,
    ConversationRows,
    KeptLines,
    OpenSection,
    QtToadApp,
)

class QtBusSwitcher(BusListing, QFrame):
    """The modal-style bus switcher Qt opens from the hamburger.

    Reuses the same `BusRow` items + `BusAddress` input Welcome renders. The
    only new widget is this QFrame container; its tree is a plain
    `ConversationRows` (the shared Qt tree type), populated with `BusRow`s
    through the shared `BusListing.redraw`/`KeptLines` flow Welcome uses.
    """

    def __init__(self, window: QtToadApp) -> None:
        super().__init__(window)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._host = window
        self._rows: tuple[PickerRow, ...] = ()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(UiGap.frame, UiGap.loose, UiGap.frame, UiGap.loose)
        outer.setSpacing(UiGap.loose)

        self._prompt = QLabel(BusSwitcherPrompt.initial(), self)
        self._prompt.setWordWrap(True)
        outer.addWidget(self._prompt)

        # Same tree type Welcome uses so rows render identically. Activation
        # routes through `SidebarItem.activate` → `BusRow.activate` →
        # `self.choice.chosen(window)` → the shared `BusPickerHost` dispatch.
        self._tree = ConversationRows(window)
        self._tree.itemClicked.disconnect()
        self._tree.itemClicked.connect(self._row_clicked)
        outer.addWidget(self._tree, 1)

        self._address = BusAddress(window)
        self._address.returnPressed.connect(self.hide_switcher)
        outer.addWidget(self._address)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self._close = QtPushButton("Close", self)
        self._close.clicked.connect(self.hide_switcher)
        close_row.addWidget(self._close)
        outer.addLayout(close_row)

        self.hide()

    # ---- BusListing shared contract ----

    def picker_host(self) -> BusPickerHost:
        return self._host

    def show_rows(self, rows: tuple[PickerRow, ...]) -> None:
        """Redraw the tree with these rows under a single "Buses" section — mirrors
        `Welcome.draw_lines` at `src/toad/qt/window.py` so the two paths render
        BusRow items identically."""
        self._rows = rows
        def draw(top: KeptLines) -> None:
            with top.group(OpenSection(self.buses_title)) as section:
                for choice in rows:
                    section.keep(BusRow(choice))
        self._tree.redraw(draw)
        for index in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(index).setExpanded(True)

    def say_discovery(self, found: int) -> None:
        """Shared text (`BusSwitcherPrompt.discovery`) so Qt matches Textual."""
        self._prompt.setText(BusSwitcherPrompt.discovery(found))

    def say_failure(self, reason: str) -> None:
        self._prompt.setText(BusSwitcherPrompt.failure(reason))

    # ---- Qt show/hide lifecycle ----

    def show_switcher(self) -> None:
        """Mirrors Textual's `BusChoices.ask_again` on mount: the reader opened this
        to choose a bus, so ask the tailnet again, and relist with what we already
        know meanwhile. Registers as a listing so `QtToadApp.tailnet_answered`
        routes answers here too."""
        self._prompt.setText(BusSwitcherPrompt.initial())
        self.relist()
        self._host.register_bus_listing(self)
        self._host.discover_buses()
        self.show()
        self._address.setFocus()

    def hide_switcher(self) -> None:
        self._host.deregister_bus_listing(self)
        self.hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.hide_switcher()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---- row + address handlers ----

    def _row_clicked(self, item) -> None:
        """Polymorphic switcher activation: `BusRow` closes the switcher and switches onto
        the chosen bus; section headers toggle open/closed without dismissing."""
        item.activate_in_switcher(self, self._host)
