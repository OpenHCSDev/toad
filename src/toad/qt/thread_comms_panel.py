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
from agent_comms.registry.relationships import (
    RelationshipEntry,
    RelationshipGroup,
    SortableRelationshipGroup,
    ThreadCommsSnapshot,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from toad.client.relationship_tree_state import RelationshipTreeState
from toad.thread_identity import NoThreadIdentity, SessionIdentity


class QtRelationshipSort(QToolButton):
    """Header control for a `ThreadCommsSnapshot`'s sortable groups. Lists every
    `ThreadSort` family member in a menu; selecting one calls
    `RelationshipReads.set_relationship_order` for each sortable group in the snapshot.
    Mirrors Textual's `RelationshipSort(SortControl[ThreadSort])` behaviour by sharing
    both the order family (`ThreadSort.members_with`) and the write path."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setAutoRaise(True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setText("Sort")
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        for order in ThreadSort.members_with(ThreadSort):
            action = QAction(order.title, self._menu)
            action.triggered.connect(partial(self._picked, order))
            self._menu.addAction(action)
        self._panel: QtThreadCommsPanel | None = None
        self._groups: tuple[SortableRelationshipGroup, ...] = ()
        self._current_order: type[ThreadSort] | None = None

    def bind(self, panel: QtThreadCommsPanel) -> None:
        self._panel = panel

    def update_groups(self, groups: tuple[SortableRelationshipGroup, ...]) -> None:
        self._groups = groups
        orders = {group.order for group in groups}
        self._current_order = next(iter(orders)) if len(orders) == 1 else None
        self.setText(f"Sort: {self._current_order.title}" if self._current_order else "Sort")

    def _picked(self, order: type[ThreadSort]) -> None:
        panel = self._panel
        if panel is None or not self._groups:
            return
        asyncio.ensure_future(panel.write_order(self._groups, order))


class QtThreadCommsPanel(QWidget):
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
        self._view = None
        self._states: dict[SessionIdentity, RelationshipTreeState] = {}
        self._snapshot: ThreadCommsSnapshot | None = None
        self._refresh_task: asyncio.Task | None = None
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 4, 8, 4)
        column.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._context = QLabel("", self)
        self._context.setWordWrap(True)
        self._context.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(self._context, 1)
        self._sort = QtRelationshipSort(self)
        self._sort.bind(self)
        header.addWidget(self._sort)
        column.addLayout(header)
        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemExpanded.connect(self._item_expanded)
        self._tree.itemCollapsed.connect(self._item_collapsed)
        column.addWidget(self._tree, 1)

    def bind(self, view) -> None:
        """Follow the conversation the tab now shows. The welcome has no identity, so the
        tree goes quiet."""
        self._view = view
        self.present()

    def present(self) -> None:
        if self._view is None:
            self._context.setText("No open conversation")
            self._tree.clear()
            return
        asyncio.ensure_future(self._refresh())

    @property
    def _thread_identity(self) -> SessionIdentity:
        if self._view is None:
            return NoThreadIdentity()
        identity = getattr(self._view, "thread_identity", None)
        return identity if identity is not None else NoThreadIdentity()

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
        if isinstance(group_type, type) and issubclass(group_type, RelationshipGroup):
            self._state.expanded[group_type] = True

    def _item_collapsed(self, item: QTreeWidgetItem) -> None:
        group_type = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(group_type, type) and issubclass(group_type, RelationshipGroup):
            self._state.expanded[group_type] = False

    async def write_order(self, groups: tuple[SortableRelationshipGroup, ...],
                          order: type[ThreadSort]) -> None:
        """Called by `QtRelationshipSort`; same write path as Textual's
        `RelationshipSort.order_writer`."""
        identity = self._thread_identity
        root = identity.root_path
        if root is None:
            return
        app = self._app()
        if app is None:
            return
        access = app.coordination_access
        service = await app.preparation.run_thread(lambda: access.observing(root))
        try:
            for group in groups:
                await app.preparation.run_thread(
                    service.set_relationship_order, identity.thread_name(), type(group), order
                )
        finally:
            if identity == self._thread_identity:
                self.present()
