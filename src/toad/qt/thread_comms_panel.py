"""Qt rendering of the thread-comms sidebar panel: relationship rows grouped by their
`RelationshipGroup` family, plus a header control for `ThreadSort`.

Reads the same `ThreadCommsSnapshot` that Textual's `ThreadCommsSidebar` reads (via
`toad.client.thread_comms_source.RelationshipReads.relationships`), and writes the sort
order through the same `RelationshipReads.set_relationship_order`. Per-session UI state
(group-expansion, selected row) survives tab switches via the toolkit-neutral
`toad.client.relationship_tree_state.RelationshipTreeState` — one state owner, two
renderers.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import ClassVar

from agent_comms.display_order import ThreadSort
from agent_comms.ui_model.message_category import MessageCategory
from agent_comms.registry.relationships import (
    RelationshipEntry,
    RelationshipGroup,
    ThreadCommsSnapshot,
)
from agent_comms.registry.relationships import SortableRelationshipGroup
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from toad.qt.session_panel import SessionPanel
from toad.client.category_selection import CategorySelection
from toad.client.relationship_tree_state import RelationshipTreeState
from toad.client.sort_control import RelationshipOrder
from toad.qt.channel_sort import QtSortButton
from toad.widgets.session_sort import ThreadSortForm
from toad.thread_identity import SessionIdentity
from toad.qt.metrics import UiGap


class QtRelationshipSort(RelationshipOrder, QtSortButton[ThreadSort]):
    """The comms panel header's relationship order, as Textual's `RelationshipSort`: the
    shared `RelationshipOrder` labels it from the snapshot's groups and writes each group."""

    def __init__(self, panel: QtThreadCommsPanel) -> None:
        self._panel = panel
        super().__init__(ThreadSortForm, "relationships", panel)

    async def write_picked(self, order: type[ThreadSort]) -> None:
        await self._panel.write_order(order)


class QtThreadCommsPanel(SessionPanel, QWidget):
    spec_key: ClassVar[str] = "comms"
    """Which `ThreadSidebarPanelSpec.key` this widget renders — mirrors the TUI
    `SessionPanel.spec_key` convention so both frontends share one identity per panel."""

    """Renders a thread's relationship rows as a Qt tree: top-level items per
    `RelationshipGroup`, children per `RelationshipEntry`. The snapshot is fetched off the
    UI thread through `app.preparation.run_thread`, as Textual's `ThreadCommsSidebar` does.
    State (group-expansion, selection) is kept per `SessionIdentity` in the shared
    `RelationshipTreeState` so a reopened tab restores its prior view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._states: dict[SessionIdentity, RelationshipTreeState] = {}
        self._snapshot: ThreadCommsSnapshot | None = None
        self._refresh_task: asyncio.Task | None = None
        column = QVBoxLayout(self)
        column.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.normal)
        column.setSpacing(UiGap.normal)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._context = QLabel("", self)
        self._context.setWordWrap(True)
        self._context.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(self._context, 1)
        self._sort = QtRelationshipSort(self)
        header.addWidget(self._sort)
        column.addLayout(header)
        # One toggle per message category under the context line, as Textual's
        # `ThreadCommsSidebar` composes its `MessageFilter`s: each writes the bound view's
        # `CategorySelection`, and a view that filters nothing hides them.
        self._checks: dict[type[MessageCategory], QCheckBox] = {}
        for category in MessageCategory.members_with(MessageCategory):
            check = QCheckBox(category.label, self)
            check.toggled.connect(partial(self._category_toggled, category))
            self._checks[category] = check
            column.addWidget(check)
        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemExpanded.connect(self._item_expanded)
        self._tree.itemCollapsed.connect(self._item_collapsed)
        column.addWidget(self._tree, 1)

    @property
    def _categories(self) -> CategorySelection:
        return self._view.category_selection

    def _sync_checks(self) -> None:
        selection = self._categories
        for category, check in self._checks.items():
            check.setVisible(selection.filters)
            check.blockSignals(True)
            check.setChecked(category in selection.visible_categories)
            check.blockSignals(False)

    def _category_toggled(self, category: type[MessageCategory], on: bool) -> None:
        self._categories.set_category(category, on)
        self._sync_checks()

    def present(self) -> None:
        self._sync_checks()
        asyncio.ensure_future(self._refresh())

    @property
    def _thread_identity(self) -> SessionIdentity:
        return self._view.thread_identity

    @property
    def _state(self) -> RelationshipTreeState:
        return self._states.setdefault(self._thread_identity, RelationshipTreeState())

    async def _refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.current_task()
        try:
            identity = self._thread_identity
            root = identity.root_path
            if root is None:
                self._context.setText("No thread root")
                self._tree.clear()
                return
            app = self._app()
            if app is None:
                return
            access = app.coordination_access
            service = await app.preparation.run_thread(lambda: access.observing(root))
            if identity != self._thread_identity:
                return
            snapshot = await app.preparation.run_thread(service.relationships, identity.thread_name())
            if identity != self._thread_identity:
                return
            self._apply(snapshot)
        finally:
            self._refresh_task = None

    def _app(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "coordination_access") and hasattr(parent, "preparation"):
                return parent
            parent = parent.parent()
        return None

    def _apply(self, snapshot: ThreadCommsSnapshot) -> None:
        self._snapshot = snapshot
        suffix = " · recent window" if snapshot.history_limited else ""
        self._context.setText(f"For @{snapshot.owner}{suffix}")
        self._context.setToolTip(
            f"{snapshot.incoming_basis}\nLatest {snapshot.history_messages} wire messages"
        )
        self._sort.update_groups(snapshot.sortable_groups)
        self._tree.clear()
        state = self._state
        for group in snapshot.groups:
            group_type = type(group)
            top = QTreeWidgetItem(self._tree, [group_type.title])
            top.setData(0, Qt.ItemDataRole.UserRole, group_type)
            expanded = state.expanded.get(group_type, True)
            top.setExpanded(expanded)
            entries = tuple(group.entries.values())
            if not entries:
                empty = QTreeWidgetItem(top, [group_type.empty_text])
                empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for entry in entries:
                self._add_entry_item(top, entry)

    def _add_entry_item(self, parent_item: QTreeWidgetItem, entry: RelationshipEntry) -> None:
        display = entry.target if entry.available else f"{entry.target} (unavailable)"
        row = QTreeWidgetItem(parent_item, [display])
        if entry.detail:
            row.setToolTip(0, entry.detail)
        row.setData(0, Qt.ItemDataRole.UserRole, entry)

    def _item_expanded(self, item: QTreeWidgetItem) -> None:
        group_type = item.data(0, Qt.ItemDataRole.UserRole)
        if RelationshipGroup.is_group_type(group_type):
            self._state.expanded[group_type] = True

    def _item_collapsed(self, item: QTreeWidgetItem) -> None:
        group_type = item.data(0, Qt.ItemDataRole.UserRole)
        if RelationshipGroup.is_group_type(group_type):
            self._state.expanded[group_type] = False

    async def write_order(self, order: type[ThreadSort]) -> None:
        """`QtRelationshipSort`'s pick: every sortable group of the snapshot shown takes the
        order, through the shared `RelationshipOrder` write, as Textual's sort writes it."""
        snapshot = self._snapshot
        if snapshot is None:
            raise ValueError("Relationship ordering is not available yet")
        identity = self._thread_identity
        app = self._app()
        access = app.coordination_access
        service = await app.preparation.run_thread(lambda: access.observing(identity.root_path))
        try:
            await self._sort.write_relationship_order(
                app.preparation, service, identity, snapshot.sortable_groups, order)
        finally:
            if identity == self._thread_identity:
                self.present()
