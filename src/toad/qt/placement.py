"""The Qt sidebars' Toad-specific pieces; the surfaces themselves are `toad.qt.side_bar`.

  - `SessionArrangementStore`: the phone's per-run arrangement store (the desktop uses the
    Toad settings file; Android has no settings file in its import reach).
  - `ThreadSettingsPane`: the thread sidebar's content. Iterates the shared panel roster
    declared in `toad.thread_sidebar_declarations` so the sections Qt draws match the panels
    Textual composes; every roster entry has a Qt body (a `ThreadSidebarPanelBody`), and an
    entry without one fails loud when the pane is built.

Text that will not fit the 412 px width is an ElidedLine, so a long thread name shows its
overflow rather than widening the window.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from agent_comms.ui_model.message_category import MessageCategory, all_categories
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QGroupBox, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from toad.client.context_intent import ContextTreeIntent
from toad.qt.context_panel import QtContextExplorer
from toad.qt.coordination_panel import QtCoordinationStatus
from toad.qt.session_panel import SessionPanel
from toad.qt.plan_panel import QtPlan
from toad.qt.project_panel import QtProjectPanel
from toad.qt.thread_comms_panel import QtThreadCommsPanel
from toad.sidebar_layout import ArrangementStore
from toad.terminal_origin import TerminalLayout
from toad.thread_identity import NoThreadIdentity, SessionIdentity
from toad.thread_sidebar_declarations import (
    THREAD_SIDEBAR_PANELS, ThreadSidebarPanelBody, ThreadSidebarPanelSpec, panel_specs_for_view,
)
from toad.qt.metrics import UiGap

__all__ = ["SessionArrangementStore", "ThreadSettingsPane"]


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


class _CategoryFilter(SessionPanel, QWidget):
    """The message-category toggle list. Lives in its own widget so `ThreadSettingsPane`
    can compose it as one section among the sidebar panels declared in the shared roster.
    `_view` and `bind()` come from `SessionPanel`; `present()` is the per-panel override."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        column = QVBoxLayout(self)
        column.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.normal)
        column.setSpacing(UiGap.tight)
        self._checks: dict[type[MessageCategory], QCheckBox] = {}
        for category in MessageCategory.members_with(MessageCategory):
            check = QCheckBox(category.label, self)
            check.toggled.connect(partial(self._toggled, category))
            self._checks[category] = check
            column.addWidget(check)

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


class ThreadSettingsPane(QWidget):
    """The open thread's sidebar content. Composes one section per panel in the shared
    roster (`toad.thread_sidebar_declarations.THREAD_SIDEBAR_PANELS`) so the Qt sidebar
    reflects the same structure Textual's `SessionThreadSidebar` composes — no hand-rolled
    mirror of the panel list, one source of truth. Each roster entry's body is the Qt
    panel whose `spec_key` names it; a roster entry with no body raises KeyError here.

    `bind(view)` routes the conversation's view at every section that reads or writes it.
    """

    def __init__(self, parent: QWidget | None = None, *, project_path: Path) -> None:
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
        column.setSpacing(UiGap.normal)
        self._category_filter = _CategoryFilter(self._content)
        self._coordination_status = QtCoordinationStatus(self._content)
        self._comms_panel = QtThreadCommsPanel(self._content)
        self._plan_panel = QtPlan(self._content)
        self._project_panel = QtProjectPanel(project_path, parent=self._content)
        # Shared per-thread context intents — survives widget retirement, matches
        # Textual's `ContextSessionPanel.intents`.
        self._context_intents: dict[SessionIdentity, ContextTreeIntent] = {}
        self._context_panel = QtContextExplorer(self._context_intents, self._content)
        # One widget per spec.key: each Qt panel class declares its own `spec_key`
        # ClassVar (same convention Textual's `SessionPanel.spec_key` uses). The
        # dispatch in `_panel_body` reads this map instead of restating a chain of
        # `if spec.key == "...": return self._x_panel`.
        panels: tuple[ThreadSidebarPanelBody, ...] = (
            self._coordination_status,
            self._comms_panel,
            self._plan_panel,
            self._context_panel,
            self._project_panel,
        )
        self._bodies_by_key: dict[str, QWidget] = {
            panel.spec_key: panel for panel in panels
        }
        self._section_bodies: dict[str, QWidget] = {}
        # The session view is the default; a conversation / DM tab trims the roster via
        # `bind_view_kind` when its ACP tab calls in. Both views carry Coordination and
        # Comms; session view adds Plan, Project, Context.
        for spec in panel_specs_for_view(is_session=True):
            section = QGroupBox(spec.heading, self._content)
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, UiGap.tight, 0, 0)
            section_layout.setSpacing(0)
            body = self._panel_body(spec, section)
            section_layout.addWidget(body)
            self._section_bodies[spec.key] = body
            # A spec that declares flex=True fills the remaining vertical space
            # (Textual reads the same flag from the shared roster); without a
            # stretch factor QVBoxLayout would hand it only its sizeHint.
            column.addWidget(section, 1 if spec.flex else 0)
        self._categories_section = QGroupBox("Message categories", self._content)
        categories_layout = QVBoxLayout(self._categories_section)
        categories_layout.setContentsMargins(0, UiGap.tight, 0, UiGap.tight)
        categories_layout.setSpacing(0)
        categories_layout.addWidget(self._category_filter)
        column.addWidget(self._categories_section)
        # Add a terminal stretch only when nothing above already stretches, so a
        # flex=True section (Project) can fill the pane without a competing
        # empty stretch below taking half the space.
        if not any(spec.flex for spec in panel_specs_for_view(is_session=True)):
            column.addStretch(1)
        scroll.setWidget(self._content)

    def _panel_body(self, spec: ThreadSidebarPanelSpec, parent: QWidget) -> QWidget:
        """The Qt panel whose `spec_key` names this roster entry. An entry with no Qt body
        is a missing port, and building the pane fails on it."""
        return self._bodies_by_key[spec.key]

    def bind(self, view) -> None:
        """Follow the conversation the tab now shows; the welcome has none (view is None,
        per `_bind_thread_pane`), so the toggles go quiet. Panels that read / write the
        view receive it here."""
        self._category_filter.bind(view)
        self._coordination_status.apply(
            view.thread_identity if view is not None else NoThreadIdentity()
        )
        self._comms_panel.bind(view)
        self._plan_panel.bind(view)
        self._context_panel.bind(view)

    def present(self) -> None:
        self._category_filter.present()
        self._comms_panel.present()
        self._context_panel.present()
