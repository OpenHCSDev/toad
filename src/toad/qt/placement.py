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

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QScrollArea, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from toad.client.context_intent import ContextTreeIntent
from toad.client.session_scope import NoConversationView
from toad.client.session_tracker import SidebarState
from toad.client.settings_schema import ObjectSettingRow
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sidebar_panels import ObjectPropertiesPanel
from toad.qt.context_panel import QtContextExplorer
from toad.qt.coordination_panel import QtCoordinationStatus
from toad.qt.plan_panel import QtPlan
from toad.qt.project_panel import QtProjectPanel
from toad.qt.settings_screen import QtSettingsEditor
from toad.qt.sidebar_panel import QtPanelEntry, QtPanelMenu, QtSidebarShell
from toad.qt.thread_comms_panel import QtThreadCommsPanel
from toad.sidebar_layout import ArrangementStore
from toad.terminal_origin import TerminalLayout
from toad.thread_identity import SessionIdentity
from toad.thread_sidebar_declarations import ThreadSidebarContents, panel_specs_for_view
from toad.qt.metrics import UiGap

__all__ = ["QtObjectProperties", "SessionArrangementStore", "ThreadSettingsPane"]


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


class QtObjectProperties(ObjectPropertiesPanel, QScrollArea, metaclass=PyQtWidgetMeta):
    """One setting of the viewed object as a settings-pane page, as Textual's
    `ObjectProperties`: each leaf of the field is a row the shared settings editors draw,
    writing through the view's configuration (`ObjectSettingRow`). The rows scroll when
    they outgrow the sidebar."""

    def __init__(self, field, app, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.field = field
        rows = QWidget(self)
        rows.setWindowFlags(Qt.WindowType.Widget)
        form = QFormLayout(rows)
        form.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.normal)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        for row in ObjectSettingRow.rows(field, app.saved_settings):
            label = QLabel(row.label, rows)
            label.setWordWrap(True)
            label.setToolTip(row.help)
            form.addRow(label, QtSettingsEditor.for_row(row, app, rows))
        self.setWidget(rows)


class ThreadSettingsPane(ThreadSidebarContents[QtPanelEntry], QtSidebarShell, metaclass=PyQtWidgetMeta):
    """The open view's sidebar content, as Textual's `ThreadSidebar`: the search over its
    panels, one picked at a time (`QtPanelMenu`). The entries are the shared roster
    (`THREAD_SIDEBAR_PANELS`, each drawn by the Qt panel whose `spec_key` names it) and then
    each of the view's own settings (`ViewSettingsOwner.configuration_fields`), as
    `ThreadSidebar.panel_entries` lists them: a setting declared once shows on both frontends
    with no Qt code. The search filters the panels' rows (the Comms relationships)."""

    def __init__(self, app, parent: QWidget | None = None, *, project_path: Path) -> None:
        self.app = app
        search = SidebarFilter()
        self.menu = QtPanelMenu(SidebarState())
        super().__init__(search, self.menu, parent)
        self._coordination_status = QtCoordinationStatus(self)
        self._comms_panel = QtThreadCommsPanel(search, self)
        self._plan_panel = QtPlan(self)
        self._project_panel = QtProjectPanel(project_path, parent=self)
        # Shared per-thread context intents — survive widget retirement, as Textual's
        # `ContextSessionPanel.intents`.
        self._context_intents: dict[SessionIdentity, ContextTreeIntent] = {}
        self._context_panel = QtContextExplorer(self._context_intents, self)
        bodies = {panel.spec_key: panel for panel in (
            self._coordination_status, self._comms_panel, self._plan_panel,
            self._context_panel, self._project_panel)}
        controls = {QtThreadCommsPanel.spec_key: (self._comms_panel.sort,)}
        # A roster entry with no Qt body is a missing port: building the pane fails on it.
        self._roster = tuple(
            QtPanelEntry(spec.panel, bodies[spec.key], controls.get(spec.key, ()), type(bodies[spec.key]))
            for spec in panel_specs_for_view(is_session=True))
        self._view = NoConversationView()

    def bind(self, view) -> None:
        """Follow the view the tab now shows: a conversation, or the welcome, whose
        `NoConversationView` answers absent members. Every panel takes the view as it is,
        and the view's own settings follow the roster. The entries are listed again only
        when the view changes: the window re-binds the same view on every layout pass."""
        listed = view is self._view
        self._view = view
        self._coordination_status.identity_changed(view.thread_identity)
        self._comms_panel.bind(view)
        self._plan_panel.bind(view)
        self._context_panel.bind(view)
        if not listed:
            self.menu.show_entries(self.thread_entries(view))

    def roster_entries(self) -> tuple[QtPanelEntry, ...]:
        return self._roster

    def setting_entries(self, view) -> tuple[QtPanelEntry, ...]:
        return tuple(
            QtPanelEntry(view.field_panel(field), QtObjectProperties(field, self.app), (), field.path)
            for field in view.configuration_fields())

    def present(self) -> None:
        self._comms_panel.present()
        self._context_panel.present()
