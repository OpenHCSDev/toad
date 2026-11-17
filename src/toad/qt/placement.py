"""The Qt phone's sidebar: the toggle bar and the pane it shows, re-exported from formbridge.

Toad draws a sidebar as a toggle bar — an arrow and the pane's heading — with the move and
float controls inside the pane it opens, not on the bar. formbridge owns the three reusable
Qt widgets (QtPlacementControl, SidebarPane, SidebarToggle); this module keeps only what is
Toad-specific:

  - `SessionArrangementStore`: the phone's per-run arrangement store (the desktop uses the
    Toad settings file; Android has no settings file in its import reach).
  - `ThreadSettingsPane`: the thread sidebar's content, a per-category toggle list.

The sidebar widgets accept a `SidebarControlsOwner` to build and present their controls; the
Toad family in `toad.sidebar_layout.SidebarControlsOwner` already satisfies the formbridge
protocol by having `placement_actions()` and `present_placement_controls()` as classmethods,
so the window hands the class itself in as the owner.

Text that will not fit the 412 px width is an ElidedLine, so a long thread name shows its
overflow rather than widening the window.
"""

from __future__ import annotations

from functools import partial

from agent_comms.ui_model.message_category import MessageCategory, all_categories
from formbridge.widgets.sidebar import QtPlacementControl, SidebarPane, SidebarToggle
from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

from toad.sidebar_layout import ArrangementStore
from toad.terminal_origin import TerminalLayout

__all__ = ["QtPlacementControl", "SessionArrangementStore", "SidebarPane", "SidebarToggle",
           "ThreadSettingsPane"]


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


class ThreadSettingsPane(QWidget):
    """The open thread's view settings: which message categories its transcript shows. One
    toggle per category, drawn from the shared `MessageCategory` family and bound to the
    conversation the tab shows, so the pane reads and writes that view's own selection and
    holds no copy of it. It stands in for the Textual thread sidebar's message filter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 4, 8, 4)
        column.setSpacing(2)
        self._view = None
        self._checks: dict[type[MessageCategory], QCheckBox] = {}
        for category in MessageCategory.members_with(MessageCategory):
            check = QCheckBox(category.label, self)
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
