"""The Qt sidebars' Toad-specific pieces; the surfaces themselves are `toad.qt.side_bar`.

  - `ThreadSettingsPane`: the thread sidebar's content. Iterates the shared panel roster
    declared in `toad.thread_sidebar_declarations` so the sections Qt draws match the panels
    Textual composes; every roster entry has a Qt body (a `ThreadSidebarPanelBody`), and an
    entry without one fails loud when the pane is built.

Text that will not fit the 412 px width is an ElidedLine, so a long thread name shows its
overflow rather than widening the window.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_comms.cli_support.cli_failures import CLI_FAILURES

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from toad.client.context_intent import ContextTreeIntent
from toad.client.session_scope import NoConversationView
from toad.client.session_tracker import SidebarState
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sidebar_panels import ActionPropertiesPanel, ObjectPropertiesPanel
from toad.qt.command_form import QtCommandForm
from toad.qt.context_panel import QtContextExplorer
from toad.qt.coordination_panel import QtCoordinationStatus
from toad.qt.plan_panel import QtPlan
from toad.qt.project_panel import QtProjectPanel
from toad.qt.forms import QtObjectFieldView, QtObjectFormView
from toad.qt.sidebar_panel import QtPanelEntry, QtPanelMenu, QtSidebarShell
from toad.qt.thread_comms_panel import QtThreadCommsPanel
from toad.thread_identity import SessionIdentity
from toad.thread_sidebar_declarations import ThreadSidebarContents, panel_specs_for_view

__all__ = ["QtObjectProperties", "ThreadSettingsPane"]


class QtObjectProperties(ObjectPropertiesPanel, QScrollArea, metaclass=PyQtWidgetMeta):
    """One setting of the viewed object as a settings-pane page, as Textual's
    `ObjectProperties`: the object form over that one field (`QtObjectFormView`), so the
    section heading and description, each field's help, bounds and default, its source
    line and Reset come from the same shared field contract Textual's page draws. Edits go
    through the view's configuration. The form scrolls when it outgrows the sidebar."""

    def __init__(self, field, renderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.field = field
        self.form = QtObjectFormView(field.state, [QtObjectFieldView.from_field(field)])
        self.form.theme(renderer)
        self.setWidget(self.form.body)
        self.form.follow_state()
        self.destroyed.connect(self.form.leave_state)

    def finish(self) -> None:
        self.form.finish()

    def release_page(self) -> None:
        """The view this page edited is no longer bound."""
        self.deleteLater()


class QtActionProperties(ActionPropertiesPanel, QtCommandForm):
    """One backend configuration operation as a settings-pane page, as Textual's
    `ActionProperties`: the embedded command form, submitting through the shared writer."""

    def __init__(self, host, context, definition, fields, parent: QWidget | None = None) -> None:
        self.context = context
        super().__init__(host, definition, context.title, fields, context.observed.core, parent)
        self._drafted = False

    def showEvent(self, event) -> None:  # type: ignore[override]
        """The form asks Core for its choices once it is first picked, as Textual's
        `PanelMenu` mounts a page (and its draft opens) only when it is selected."""
        super().showEvent(event)
        if not self._drafted:
            self._drafted = True
            self.open_draft()

    def dismiss_control(self) -> None:
        """An embedded form discards its draft without closing the view, as Textual's does."""
        for path in self.state.parameters:
            self.state.reset_parameter(path)


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
        # The entries built for the bound view (its settings and actions), released when the
        # view changes; the roster panels follow every view.
        self._view_entries: tuple[QtPanelEntry, ...] = ()
        self._actions_task: asyncio.Task | None = None

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
            self._release_view_entries()
            entries = self.thread_entries(view)
            self._view_entries = entries[len(self._roster):]
            self.menu.show_entries(entries)
            self._actions_task = asyncio.ensure_future(self._load_actions(view))

    async def _load_actions(self, view) -> None:
        """The view's backend configuration operations, read off the UI loop and listed after
        its settings, as Textual's `PanelMenu.load_configuration` lists them."""
        try:
            declarations = await self.app.preparation.run_thread(view.configuration_actions)
        except CLI_FAILURES as error:
            self.app.show_error(error, "Object settings")
            return
        if view is not self._view:
            return
        actions = tuple(
            QtPanelEntry(view.action_panel(action), QtActionProperties(self.app, context, action, fields),
                         (), action.declaration)
            for context, action, fields in declarations)
        self._view_entries += actions
        self.menu.add_entries(actions)

    def _release_view_entries(self) -> None:
        if self._actions_task is not None:
            self._actions_task.cancel()
        for entry in self._view_entries:
            entry.widget.release_page()
        self._view_entries = ()

    def roster_entries(self) -> tuple[QtPanelEntry, ...]:
        return self._roster

    def setting_entries(self, view) -> tuple[QtPanelEntry, ...]:
        return tuple(
            QtPanelEntry(view.field_panel(field), QtObjectProperties(field, self.app.renderer), (), field.path)
            for field in view.configuration_fields())

    def present(self) -> None:
        self._comms_panel.present()
        self._context_panel.present()
