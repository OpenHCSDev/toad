"""The Qt phone's sidebar placement bars.

Each pane the phone shows — the channels-and-threads sidebar and the open thread's own
view settings — sits behind a bar above the tabs, exactly as Toad's phone layout draws its
two bars side by side. A bar names its pane, shows or hides it, and moves or floats it. The
move and float are the shared policy: this draws `SidebarLayout`, the one owner the Textual
workspace reads for its own arrangement, over the session store below; the phone keeps no
copy of the move and float logic, only the store its settings file does not reach.

A phone is one column wide, so only the top and bottom edges and floating make sense; the
left and right columns a wide terminal offers are never drawn. Text that will not fit the
412 px width is an ElidedLine, so a long thread name shows its overflow rather than widening
the window.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from agent_comms.ui_model.message_category import MessageCategory, all_categories
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from pyqt_reactive.widgets.fitted_text import ElidedLine

from toad.sidebar_layout import ArrangementStore, SidebarLayout
from toad.sidebar_placement import (
    BottomSidebarEdge,
    SidebarEdge,
    SidebarPlacement,
    TopSidebarEdge,
)
from toad.terminal_origin import TerminalLayout

# The edges a phone offers, top first: a bar moves between them, and floating is the third
# placement, drawn as the Float control rather than an edge.
PHONE_EDGES: tuple[type[SidebarEdge], ...] = (TopSidebarEdge, BottomSidebarEdge)


class SessionArrangementStore(ArrangementStore):
    """The phone's sidebar arrangement for this run. The desktop keeps its arrangement in the
    one Toad setting over toad.json; the phone client has no settings file in its import
    reach, so it holds the arrangement for the session and starts each run from the roles'
    own defaults. SidebarLayout is still the one owner of the move and float policy over it."""

    def __init__(self) -> None:
        self._terminals: tuple[TerminalLayout, ...] = ()

    def current_terminals(self) -> tuple[TerminalLayout, ...]:
        return self._terminals

    def store_terminals(self, terminals: tuple[TerminalLayout, ...]) -> None:
        self._terminals = terminals


class PlacementBar(QWidget):
    """One pane's bar: its toggle, its move arrows and its float control, over the shared
    `SidebarLayout`. The bar owns no placement state; it reads the layout and, on a press,
    asks the layout to move, float or the window to show the pane, then the window lays the
    panes out again and saves the arrangement."""

    def __init__(
        self,
        layout: SidebarLayout,
        identity: type[SidebarPlacement],
        *,
        heading: Callable[[], str],
        shown: Callable[[], bool],
        toggled: Callable[[], None],
        rearranged: Callable[[], None],
    ) -> None:
        super().__init__()
        self._layout = layout
        self._identity = identity
        self._heading = heading
        self._shown = shown
        self._toggled = toggled
        self._rearranged = rearranged

        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)

        self._moves: dict[type[SidebarEdge], QToolButton] = {}
        for edge in PHONE_EDGES:
            button = self._control(edge.symbol, partial(self._move, edge))
            self._moves[edge] = button
            row.addWidget(button)

        self._toggle = QToolButton()
        self._toggle.setAutoRaise(True)
        self._toggle.setMinimumHeight(40)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._toggle.clicked.connect(lambda: self._toggled())
        self._title = ElidedLine("")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(2)
        toggle_row.addWidget(self._toggle)
        toggle_row.addWidget(self._title, 1)
        toggle_row.addWidget(self._float_toggle())
        row.addLayout(toggle_row, 1)

    def _control(self, text: str, action: Callable[[], None]) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setAutoRaise(True)
        button.setMinimumSize(32, 40)
        button.clicked.connect(lambda: action())
        return button

    def _float_toggle(self) -> QToolButton:
        self._float = QToolButton()
        self._float.setAutoRaise(True)
        self._float.setMinimumSize(44, 40)
        self._float.clicked.connect(self._do_float)
        return self._float

    def _move(self, edge: type[SidebarEdge]) -> None:
        if self._layout.shift(self._identity, edge):
            self._rearranged()

    def _do_float(self) -> None:
        self._layout.float_mode(self._identity)
        self._rearranged()

    @property
    def placement(self) -> SidebarPlacement:
        return self._layout.get(self._identity)

    def present(self) -> None:
        """Draw the bar from the shared layout: the toggle names the pane and points at it,
        each move arrow offers the edge it can reach, and Float or Push names what it does."""
        placement = self.placement
        shown = self._shown()
        heading = self._heading()
        # The toggle points at its pane: a closed pane's arrow points the way the pane opens
        # (away from its edge), an open one's points back toward the edge that closes it.
        arrow = placement.side.toggle_symbol(not shown)
        self._toggle.setText(arrow)
        self._title.setText(heading)
        self._toggle.setToolTip(("Hide " if shown else "Show ") + heading)
        directions = self._layout.directions(self._identity)
        for edge, button in self._moves.items():
            shift = directions[edge]
            button.setEnabled(shift.available)
            button.setToolTip(shift.tooltip(edge))
        self._float.setText("Push" if placement.floating else "Float")
        self._float.setToolTip(
            "Push the conversation text aside" if placement.floating
            else "Float over the conversation text")


class ThreadSettingsPane(QWidget):
    """The open thread's view settings: which message categories its transcript shows. One
    toggle per category, drawn from the shared `MessageCategory` family and bound to the
    conversation the tab shows, so the pane reads and writes that view's own selection and
    holds no copy of it. It stands in for the Textual thread sidebar's message filter."""

    def __init__(self) -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 4, 8, 4)
        column.setSpacing(2)
        self._view = None
        self._checks: dict[type[MessageCategory], QCheckBox] = {}
        for category in MessageCategory.members_with(MessageCategory):
            check = QCheckBox(category.label)
            check.toggled.connect(partial(self._toggled, category))
            self._checks[category] = check
            column.addWidget(check)

    def bind(self, view) -> None:
        """Follow the conversation the tab now shows; the welcome has none, so the toggles go
        quiet. A bound pane reads the view's selection and reflects it in the checks."""
        self._view = view
        self.present()

    def present(self) -> None:
        view = self._view
        selected = view.visible_categories if view is not None else all_categories()
        for category, check in self._checks.items():
            check.setEnabled(view is not None)
            check.blockSignals(True)
            check.setChecked(category in selected)
            check.blockSignals(False)

    def _toggled(self, category: type[MessageCategory], on: bool) -> None:
        if self._view is not None:
            self._view.set_category(category, on)
