"""The Qt phone's sidebar: the toggle bar and the pane it shows, re-exported from formbridge.

Toad draws a sidebar as a toggle bar — an arrow and the pane's heading — with the move and
float controls inside the pane it opens, not on the bar. formbridge owns the three reusable
Qt widgets (QtPlacementControl, SidebarPane, SidebarToggle); this module keeps only what is
Toad-specific:

  - `SessionArrangementStore`: the phone's per-run arrangement store (the desktop uses the
    Toad settings file; Android has no settings file in its import reach).
  - `ThreadSettingsPane`: the thread sidebar's content. Iterates the shared panel roster
    declared in `toad.thread_sidebar_declarations` so the sections Qt draws match the panels
    Textual composes — a new panel added to the roster shows up on both frontends. Only the
    message-category filter has a real Qt body today; the other sections carry a placeholder
    until each per-panel Qt port lands.

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
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QGroupBox, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from toad.qt.coordination_panel import QtCoordinationStatus
from toad.qt.thread_comms_panel import QtThreadCommsPanel
from toad.sidebar_layout import ArrangementStore
from toad.terminal_origin import TerminalLayout
from toad.thread_identity import NoThreadIdentity
from toad.thread_sidebar_declarations import (
    THREAD_SIDEBAR_PANELS, ThreadSidebarPanelSpec, panel_specs_for_view,
)

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


class _CategoryFilter(QWidget):
    """The message-category toggle list. Lives in its own widget so `ThreadSettingsPane`
    can compose it as one section among the sidebar panels declared in the shared roster."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
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


def _placeholder_body(spec: ThreadSidebarPanelSpec, parent: QWidget) -> QWidget:
    """The body a sidebar panel shows on Qt until its widget port lands. Carries the shared
    spec's heading in context so a reader knows what the section will become."""
    body = QLabel(f"{spec.heading} — port to Qt pending (view on desktop Toad for now)",
                  parent)
    body.setWordWrap(True)
    body.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    body.setContentsMargins(8, 4, 8, 8)
    return body


class ThreadSettingsPane(QWidget):
    """The open thread's sidebar content. Composes one section per panel in the shared
    roster (`toad.thread_sidebar_declarations.THREAD_SIDEBAR_PANELS`) so the Qt sidebar
    reflects the same structure Textual's `SessionThreadSidebar` composes — no hand-rolled
    mirror of the panel list, one source of truth. Only the message-category filter has a
    real Qt body yet; the other sections carry a placeholder until each per-panel port
    lands as its own follow-up PR.

    `bind(view)` routes the conversation's view at the sections that read / write it —
    today that is the category filter; a future Plan / Project / Context panel port will
    receive the same view and present its own content.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)
        self._content = QWidget(scroll)
        self._content.setWindowFlags(Qt.WindowType.Widget)
        column = QVBoxLayout(self._content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        self._category_filter = _CategoryFilter(self._content)
        self._coordination_status = QtCoordinationStatus(self._content)
        self._comms_panel = QtThreadCommsPanel(self._content)
        self._section_bodies: dict[str, QWidget] = {}
        # The session view is the default; a conversation / DM tab trims the roster via
        # `bind_view_kind` when its ACP tab calls in. Both views carry Coordination and
        # Comms; session view adds Plan, Project, Context.
        for spec in panel_specs_for_view(is_session=True):
            section = QGroupBox(spec.heading, self._content)
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 2, 0, 0)
            section_layout.setSpacing(0)
            body = self._panel_body(spec, section)
            section_layout.addWidget(body)
            self._section_bodies[spec.key] = body
            column.addWidget(section)
        self._categories_section = QGroupBox("Message categories", self._content)
        categories_layout = QVBoxLayout(self._categories_section)
        categories_layout.setContentsMargins(0, 2, 0, 2)
        categories_layout.setSpacing(0)
        categories_layout.addWidget(self._category_filter)
        column.addWidget(self._categories_section)
        column.addStretch(1)
        scroll.setWidget(self._content)

    def _panel_body(self, spec: ThreadSidebarPanelSpec, parent: QWidget) -> QWidget:
        """The body for a given panel key; ported Qt panels return their real widget,
        unported ones fall through to `_placeholder_body`."""
        if spec.key == "coordination":
            return self._coordination_status
        if spec.key == "comms":
            return self._comms_panel
        return _placeholder_body(spec, parent)

    def bind(self, view) -> None:
        """Follow the conversation the tab now shows; the welcome has none, so the toggles
        go quiet. Panels that read / write the view receive it here; today the category
        filter, the coordination status and the comms tree do so, future ports (Plan /
        Project / Context) will receive it through the same hook."""
        self._category_filter.bind(view)
        identity = getattr(view, "thread_identity", None) or NoThreadIdentity()
        self._coordination_status.apply(identity)
        self._comms_panel.bind(view)

    def present(self) -> None:
        self._category_filter.present()
        self._comms_panel.present()
