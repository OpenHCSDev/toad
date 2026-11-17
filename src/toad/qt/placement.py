"""The Qt phone's sidebar: a toggle bar and the pane it shows.

Toad draws a sidebar as a toggle bar — an arrow and the pane's heading — with the move and
float controls inside the pane it opens, not on the bar. The phone follows that: each bottom
bar is only ``↑ heading ↑``; the arrows and Float live in the expanded pane. Those controls
come from the one SidebarPlacementAction family through SidebarControlsOwner, the same owner
the Textual sidebar inherits, so the two frontends cannot offer different controls or filter
them by a different rule. Qt draws only the widgets.

Text that will not fit the 412 px width is an ElidedLine, so a long thread name shows its
overflow rather than widening the window.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from agent_comms.ui_model.message_category import MessageCategory, all_categories
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine

from toad.sidebar_layout import (
    ArrangementStore,
    PlacementControl,
    SidebarControlsOwner,
    SidebarLayout,
    SidebarPlacementAction,
)
from toad.sidebar_placement import SidebarPlacement
from toad.terminal_origin import TerminalLayout


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


class QtPlacementControl(QToolButton, PlacementControl, metaclass=PyQtWidgetMeta):
    """One placement control as a Qt button: an arrow that moves the pane to its edge, or
    Float/Push. Pressing it applies the action to the shared layout, exactly as the Textual
    SidebarAction does; the family owns what the press does and how the control reads."""

    def __init__(self, action: SidebarPlacementAction, layout: SidebarLayout,
                 identity: type[SidebarPlacement], applied: Callable[[], None]) -> None:
        super().__init__()
        self.action = action
        self._layout = layout
        self._identity = identity
        self._applied = applied
        self.setText(action.label)
        self.setAutoRaise(True)
        self.setMinimumHeight(36)
        self.clicked.connect(self._apply)

    def _apply(self) -> None:
        self.action.apply(self._layout, self._identity)
        self._applied()

    def set_shown(self, shown: bool) -> None:
        self.setVisible(shown)

    def set_label(self, label: str) -> None:
        self.setText(label)

    def set_tooltip(self, tooltip: str) -> None:
        self.setToolTip(tooltip)


class SidebarPane(QWidget, SidebarControlsOwner):
    """A sidebar's expanded pane: the placement controls over its content. The controls are
    built from SidebarControlsOwner.placement_actions() and drawn by present_placement_controls,
    so every arrow and Float is the family's, filtered by the one directions rule. The toggle
    bar shows and hides this pane; the move and float live here, as the Textual layout controls
    live inside the pane and not on its toggle."""

    def __init__(self, layout: SidebarLayout, identity: type[SidebarPlacement],
                 content: QWidget, *, applied: Callable[[], None]) -> None:
        super().__init__()
        self._layout = layout
        self._identity = identity
        self.content = content
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        controls = QHBoxLayout()
        controls.setContentsMargins(2, 0, 2, 0)
        controls.setSpacing(2)
        self._controls = [
            QtPlacementControl(action, layout, identity, applied)
            for action in self.placement_actions()
        ]
        for control in self._controls:
            controls.addWidget(control)
        controls.addStretch(1)
        column.addLayout(controls)
        column.addWidget(content, 1)

    def present(self) -> None:
        self.present_placement_controls(self._controls, self._layout, self._identity)


class SidebarToggle(QWidget):
    """A sidebar's bar: an arrow and the pane's heading, nothing else. A press shows or hides
    the pane; the arrow points the way the pane opens, as the Textual toggle draws it."""

    def __init__(self, layout: SidebarLayout, identity: type[SidebarPlacement], *,
                 heading: Callable[[], str], shown: Callable[[], bool],
                 toggled: Callable[[], None]) -> None:
        super().__init__()
        self._layout = layout
        self._identity = identity
        self._heading = heading
        self._shown = shown
        self._toggled = toggled
        self.setMinimumHeight(40)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(4)
        self._left = QLabel()
        self._right = QLabel()
        self._title = ElidedLine("")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._left)
        row.addWidget(self._title, 1)
        row.addWidget(self._right)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._toggled()
        else:
            super().mousePressEvent(event)

    def present(self) -> None:
        placement = self._layout.get(self._identity)
        shown = self._shown()
        heading = self._heading()
        arrow = placement.side.toggle_symbol(not shown)
        self._left.setText(arrow)
        self._right.setText(arrow)
        self._title.setText(heading)
        self.setToolTip(("Hide " if shown else "Show ") + heading)


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
