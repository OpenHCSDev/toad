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
from functools import partial
from pathlib import Path

from agent_comms.cli_support.cli_failures import CLI_FAILURES
from agent_comms.registry.agent_settings_wire import AgentSettingsScope

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from ui_theme.scheme import FloatHoverToneColour, MutedColour

from toad.client import platform as toad_platform
from toad.client.agent_settings_state import (
    AgentScopeState,
    AgentSettingsPanel,
    scope_label,
)
from toad.client.context_intent import ContextTreeIntent
from toad.client.menu_entry import MenuEntry
from toad.client.session_scope import NoConversationView
from toad.client.session_tracker import SidebarState
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sidebar_panels import ActionPropertiesPanel, ObjectPropertiesPanel, ViewActionsPanel
from toad.qt.command_form import QtCommandForm
from toad.qt.context_panel import QtContextExplorer
from toad.qt.coordination_panel import QtCoordinationStatus
from toad.qt.menu import QtMenuRow, platform_input
from toad.qt.metrics import delete_layout_widgets
from toad.qt.plan_panel import QtPlan
from toad.qt.project_panel import QtProjectPanel
from toad.qt.forms import QtObjectFieldView, QtObjectFormView
from toad.qt.sidebar_panel import QtPanelEntry, QtPanelMenu, QtSidebarShell
from toad.qt.thread_comms_panel import QtThreadCommsPanel
from toad.thread_identity import SessionIdentity
from toad.thread_sidebar_declarations import CommsSidebarPanel, ThreadSidebarContents, ThreadSidebarPanel

__all__ = [
    "QtAgentSettingsProperties",
    "QtObjectProperties",
    "QtViewActions",
    "ThreadSettingsPane",
]


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


class QtViewActions(ViewActionsPanel, QScrollArea, metaclass=PyQtWidgetMeta):
    """The viewed object's right-click options inside the view settings bar, reusing
    `QtMenuRow` so every action renders and activates identically to right-click."""

    def __init__(self, view, renderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input_modality = platform_input()
        self._view = view
        self._renderer = renderer
        self._loaded = False
        self._load_task: asyncio.Task | None = None
        self._rows = QWidget(self)
        self._rows.setObjectName("toad-view-actions-rows")
        self._layout = QVBoxLayout(self._rows)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        self.setWidget(self._rows)
        renderer.themed(self, self.paint_colours)

    def paint_colours(self) -> None:
        hover = self._renderer.theme(FloatHoverToneColour)
        muted = self._renderer.theme(MutedColour)
        modality = toad_platform.host.input_modality
        self.setStyleSheet(
            "#toad-view-actions-rows { background: transparent; border: none; }"
            "QPushButton { background: transparent; border: none; border-radius: 0; padding: 0; text-align: left; }"
            + modality.hover_or_pressed("QPushButton", f"background: {hover};")
            + f"#toad-menu-description, #toad-view-actions-empty {{ color: {muted}; }}"
        )

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._load_task = asyncio.ensure_future(self.refresh_entries())

    async def refresh_entries(self) -> None:
        try:
            entries = await self._view.view_menu_entries()
        except CLI_FAILURES as error:
            self._view.app.show_error(error, "View actions")
            return
        self.show_entries(entries)

    def show_entries(self, entries: tuple[MenuEntry, ...]) -> None:
        delete_layout_widgets(self._layout)
        if not entries:
            empty = QLabel("No actions for this view.", self._rows)
            empty.setObjectName("toad-view-actions-empty")
            self._layout.addWidget(empty)
        else:
            for entry in entries:
                self._layout.addWidget(QtMenuRow(entry, self, self._chose, parent=self._rows))
        self._layout.addStretch(1)

    def _chose(self, entry: MenuEntry) -> None:
        entry.run()

    def finish(self) -> None:
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()

    def release_page(self) -> None:
        self.finish()
        self.deleteLater()


class QtAgentSettingsProperties(AgentSettingsPanel, QWidget, metaclass=PyQtWidgetMeta):
    """Scoped Core agent settings (Global -> Project -> [Channel] -> Thread) over QtObjectFormView."""

    def __init__(self, app, view, renderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.init_agent_settings(app, view)
        self._renderer = renderer
        self._loaded = False
        self._alive = True
        self._tasks: set[asyncio.Task] = set()
        self._form: QtObjectFormView | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.scope_combo = QComboBox(self)
        self.scope_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.scope_combo.setMinimumContentsLength(8)
        self.scope_combo.activated.connect(self._scope_activated)
        self.scope_combo.hide()
        layout.addWidget(self.scope_combo)

        self.status_label = QLabel("Loading agent settings…", self)
        self.status_label.setWordWrap(True)
        self.status_label.setEnabled(False)
        layout.addWidget(self.status_label)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.hide()
        layout.addWidget(self.scroll, 1)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._start_task(self.load_agent_settings())

    def _start_task(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _scope_activated(self, index: int) -> None:
        scope = self.scope_combo.itemData(index)
        if scope is not None:
            self.select_agent_scope(scope)

    def settings_panel_alive(self) -> bool:
        return self._alive

    async def run_settings_thread(self, work_fn):
        return await self._settings_app.preparation.run_thread(work_fn)

    def schedule_settings_persist(self, coro) -> None:
        self._start_task(coro)

    def finish_active_form(self) -> None:
        if self._form is not None:
            self._form.finish()

    def show_loading(self) -> None:
        self.scope_combo.hide()
        self.scroll.hide()
        self.status_label.setText("Loading agent settings…")
        self.status_label.show()

    def show_unavailable(self, text: str) -> None:
        self.scope_combo.hide()
        self.scroll.hide()
        self.status_label.setText(text)
        self.status_label.show()

    def show_agent_settings_chain(
        self,
        scopes: tuple[AgentSettingsScope, ...],
        selected: AgentSettingsScope,
        state: AgentScopeState,
    ) -> None:
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        chosen = 0
        for index, scope in enumerate(scopes):
            self.scope_combo.addItem(scope_label(scope), scope)
            if scope == selected:
                chosen = index
        self.scope_combo.setCurrentIndex(chosen)
        self.scope_combo.blockSignals(False)
        self.scope_combo.setVisible(len(scopes) > 1)
        self.status_label.hide()
        self.scroll.show()
        self.show_agent_scope_form(state)

    def show_agent_scope_form(self, state: AgentScopeState) -> None:
        if self._form is not None:
            self._form.leave_state()
        form = QtObjectFormView.whole(state)
        form.theme(self._renderer)
        self.scroll.setWidget(form.body)
        form.follow_state()
        self._form = form

    def finish(self) -> None:
        self.finish_active_form()

    def release_page(self) -> None:
        self._alive = False
        self.finish_active_form()
        for task in tuple(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        if self._form is not None:
            self._form.leave_state()
            self._form = None
        self.close_agent_settings_chain()
        self.deleteLater()


class ThreadSettingsPane(ThreadSidebarContents[QtPanelEntry], QtSidebarShell, metaclass=PyQtWidgetMeta):
    """The open view's sidebar content, as Textual's `ThreadSidebar`: the search over its
    panels, one picked at a time (`QtPanelMenu`). The entries come from the shared
    `ThreadSidebarPanel` family (each drawn by the Qt panel whose `panel_type` names it) and
    then each of the view's own settings (`ViewSettingsOwner.configuration_fields`), as
    `ThreadSidebar.panel_entries` lists them: a setting declared once shows on both frontends
    with no Qt code. The search filters the panels' rows (the Comms relationships)."""

    def __init__(self, app, parent: QWidget | None = None, *, project_path: Path) -> None:
        self.app = app
        search = SidebarFilter()
        self.menu = QtPanelMenu(SidebarState())
        super().__init__(search, self.menu, parent)
        self._coordination_status = QtCoordinationStatus(self)
        self._comms_panel = QtThreadCommsPanel(app, search, self)
        self._plan_panel = QtPlan(self)
        self._project_panel = QtProjectPanel(project_path, parent=self)
        # Shared per-thread context intents — survive widget retirement, as Textual's
        # `ContextSessionPanel.intents`.
        self._context_intents: dict[SessionIdentity, ContextTreeIntent] = {}
        self._context_panel = QtContextExplorer(app, self._context_intents, self)
        bodies = {panel.panel_type: panel for panel in (
            self._coordination_status, self._comms_panel, self._plan_panel,
            self._context_panel, self._project_panel)}
        controls = {CommsSidebarPanel: (self._comms_panel.sort,)}
        # A family member with no Qt body is a missing port: building the pane fails on it.
        self._roster = tuple(
            QtPanelEntry.of(panel_type.panel_spec(), bodies[panel_type],
                            controls.get(panel_type, ()), type(bodies[panel_type]))
            for panel_type in ThreadSidebarPanel.members_with(ThreadSidebarPanel))
        self._view = NoConversationView()
        # The coordination revision the panels last read the bound view's thread at.
        self._shown_revision = None
        # The entries built for the bound view (its settings and actions), released when the
        # view changes; the roster panels follow every view.
        self._view_entries: tuple[QtPanelEntry, ...] = ()
        self._actions_task: asyncio.Task | None = None

    def bind(self, view) -> None:
        """Follow the view the tab now shows: a conversation, or the welcome, whose
        `NoConversationView` answers absent members. Every panel takes the view as it is,
        and the view's own settings follow the roster. The window binds on every layout pass
        (a drag lays out every frame) and on every observation update. The panels read the
        view's thread at the bus's coordination revision, so they are bound again only when
        either changed; the view's settings and actions are listed again only for a new view."""
        revision = self.app.coordination_access.revision
        if view is self._view and revision is self._shown_revision:
            return
        listed = view is self._view
        self._view, self._shown_revision = view, revision
        self._coordination_status.identity_changed(view.thread_identity)
        self._comms_panel.bind(view)
        self._plan_panel.bind(view)
        self._context_panel.bind(view)
        if listed:
            return
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
            QtPanelEntry(view.configuration_action_panel(action), partial(QtActionProperties, self.app, context, action, fields),
                         (), action.declaration)
            for context, action, fields in declarations)
        self._view_entries += actions
        self.menu.add_entries(actions)

    def _release_view_entries(self) -> None:
        if self._actions_task is not None:
            self._actions_task.cancel()
        for entry in self._view_entries:
            entry.release_page()
        self._view_entries = ()

    def roster_entries(self) -> tuple[QtPanelEntry, ...]:
        return self._roster

    def action_entries(self, view) -> tuple[QtPanelEntry, ...]:
        return (
            QtPanelEntry(
                ViewActionsPanel.panel_spec,
                partial(QtViewActions, view, self.app.renderer),
                (),
                ViewActionsPanel.panel_identity,
            ),
        )

    def agent_settings_entries(self, view) -> tuple[QtPanelEntry, ...]:
        return (
            QtPanelEntry(
                AgentSettingsPanel.panel_spec,
                partial(QtAgentSettingsProperties, self.app, view, self.app.renderer),
                (),
                AgentSettingsPanel.panel_identity,
            ),
        )

    def setting_entries(self, view) -> tuple[QtPanelEntry, ...]:
        return tuple(
            QtPanelEntry(view.field_panel(field), partial(QtObjectProperties, field, self.app.renderer),
                         (), field.path)
            for field in view.configuration_fields())

    def present(self) -> None:
        self._comms_panel.present()
        self._context_panel.present()
