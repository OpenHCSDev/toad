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
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from toad.qt.session_panel import SessionPanel
from toad.client.category_selection import CategorySelection
from toad.client.relationship_tree_state import RelationshipPanel, RelationshipTreeState
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sort_control import RelationshipOrder
from toad.qt.channel_sort import QtSortButton
from toad.client.sort_control import ThreadSortForm
from toad.thread_identity import SessionIdentity
from toad.qt.metrics import UiGap
from toad.client.relationship_row_menu import entry_target
from toad.client.sidebar_lines import LineMenuTree, RelationshipLine

# The relationship an entry row shows; a group's own line keeps its group in UserRole.
_ENTRY = Qt.ItemDataRole.UserRole.value + 1


class QtRelationshipSort(RelationshipOrder, QtSortButton[ThreadSort]):
    """The comms panel header's relationship order, as Textual's `RelationshipSort`: the
    shared `RelationshipOrder` labels it from the snapshot's groups and writes each group."""

    def __init__(self, panel: QtThreadCommsPanel) -> None:
        self._panel = panel
        super().__init__(ThreadSortForm, "relationships", panel)

    async def write_picked(self, order: type[ThreadSort]) -> None:
        await self._panel.write_order(order)


class QtRelationshipItem(RelationshipLine, QTreeWidgetItem):
    """One relationship in the Comms panel, as Textual's `RelationshipRow`: its menu is the
    shared `RelationshipLine.menu_entries` (Open while available, Copy name)."""

    def __init__(self, panel: QtThreadCommsPanel, parent: QTreeWidgetItem, group, entry: RelationshipEntry) -> None:
        super().__init__(parent, [entry.target if entry.available else f"{entry.target} (unavailable)"])
        self.panel, self.group, self.entry = panel, group, entry
        self.target, self.available = entry_target(entry), entry.available

    @property
    def menu_tree(self) -> QtThreadCommsPanel:
        return self.panel


class QtThreadCommsPanel(LineMenuTree, RelationshipPanel, SessionPanel, QWidget, metaclass=PyQtWidgetMeta):
    spec_key: ClassVar[str] = "comms"
    """Which `ThreadSidebarPanelSpec.key` this widget renders — mirrors the TUI
    `SessionPanel.spec_key` convention so both frontends share one identity per panel."""

    """Renders a thread's relationship rows as a Qt tree: top-level items per
    `RelationshipGroup`, children per `RelationshipEntry`. The snapshot is fetched off the
    UI thread through `app.preparation.run_thread`, as Textual's `ThreadCommsSidebar` does.
    State (group-expansion, selection) is kept per `SessionIdentity` in the shared
    `RelationshipTreeState` so a reopened tab restores its prior view."""

    def __init__(self, app, search: SidebarFilter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self.setWindowFlags(Qt.WindowType.Widget)
        # The thread sidebar's search narrows the relationship rows, as Textual's
        # `ThreadCommsSidebar` follows its sidebar's search (`SearchFollower`).
        self._search = search
        search.subscribe(lambda _text: self.present())
        self._states: dict[SessionIdentity, RelationshipTreeState] = {}
        self._snapshot: ThreadCommsSnapshot | None = None
        self._refresh_task: asyncio.Task | None = None
        column = QVBoxLayout(self)
        column.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.normal)
        column.setSpacing(UiGap.normal)
        self._context = QLabel("", self)
        self._context.setWordWrap(True)
        self._context.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self._context)
        # The relationship order sits on the panel's page header, as Textual's
        # `CommsSessionPanel.make_header` puts `RelationshipSort` there.
        self.sort = QtRelationshipSort(self)
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
        # A row opens on a tap and offers Open / Copy on a right-click or a held finger,
        # as Textual's `RelationshipRow` does (`request_navigation`, `show_row_menu`).
        self._tree.itemClicked.connect(self._item_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._offer_row_menu)
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
    def thread_identity(self) -> SessionIdentity:
        return self._view.thread_identity

    async def _refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.current_task()
        try:
            identity = self.thread_identity
            root = identity.root_path
            if root is None:
                self._context.setText("No thread root")
                self._tree.clear()
                return
            app = self._app
            access = app.coordination_access
            service = await self.observed_source(access, app.preparation, root)
            if service is None or identity != self.thread_identity:
                return
            snapshot = await app.preparation.run_thread(service.relationships, identity.thread_name())
            if identity != self.thread_identity:
                return
            self._apply(snapshot)
        finally:
            self._refresh_task = None

    def show_source_unavailable(self, text: str) -> None:
        self._context.setText(text)
        self._tree.clear()

    def _apply(self, snapshot: ThreadCommsSnapshot) -> None:
        self._snapshot = snapshot
        self._context.setText(self.context_title(snapshot) + self.context_note(snapshot))
        self._context.setToolTip(self.context_tooltip(snapshot))
        self.sort.update_groups(snapshot.sortable_groups)
        self._tree.clear()
        state = self.view_state
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
            for entry in self._search.matching(entries, lambda entry: entry.target):
                self._add_entry_item(top, entry)

    def _add_entry_item(self, parent_item: QTreeWidgetItem, entry: RelationshipEntry) -> None:
        row = QtRelationshipItem(self, parent_item, parent_item.data(0, Qt.ItemDataRole.UserRole), entry)
        if entry.detail:
            row.setToolTip(0, entry.detail)
        row.setData(0, _ENTRY, entry)

    def _row_entry(self, item: QTreeWidgetItem | None) -> tuple[object, RelationshipEntry] | None:
        """The group and relationship an entry row shows; a group or "none" line shows none."""
        if item is None or item.data(0, _ENTRY) is None:
            return None
        return item.parent().data(0, Qt.ItemDataRole.UserRole), item.data(0, _ENTRY)

    def _item_clicked(self, item: QTreeWidgetItem) -> None:
        shown = self._row_entry(item)
        if shown is not None and shown[1].available:
            asyncio.ensure_future(self._open_current(*shown))

    def _offer_row_menu(self, point) -> None:
        """The relationship's own menu (`RelationshipLine.menu_entries`) for the row under
        ``point`` (viewport coordinates), in the window's menu panel; a group line has none."""
        item = self._tree.itemAt(point)
        if self._row_entry(item) is None:
            return
        asyncio.ensure_future(self._offer_read(item))

    async def _offer_read(self, item: QtRelationshipItem) -> None:
        entries = await item.menu_entries()
        self._app.offer_entries(entries)

    def relationship_opener(self, line: QtRelationshipItem):
        """Open reads the list again first (`_open_current`), as Textual's opener does."""
        return lambda: asyncio.ensure_future(self._open_current(line.group, line.entry))

    def copy_name(self, name: str) -> None:
        self._app.copy_to_clipboard(name)

    async def _open_current(self, group, entry: RelationshipEntry) -> None:
        """Open the relationship as it stands now: the list read again, and a relationship
        that changed since it was drawn is not opened (Textual's `_navigate_current`)."""
        app = self._app
        identity = self.thread_identity
        if identity.root_path is None:
            return
        if identity.root_path != app.coordination_access.observation.observed().root:
            app.show_warning("This view uses a different wire; open its matching connection to navigate.", "Comms")
            return
        service = await self.observed_source(app.coordination_access, app.preparation, identity.root_path)
        if service is None:
            return
        snapshot = await app.preparation.run_thread(service.relationships, identity.thread_name())
        current = snapshot.current_entry(group, entry)
        if current is None:
            app.show_warning("This relationship changed; refresh the list before opening it.", "Comms")
            self.present()
            return
        app.open_target(entry_target(current))

    def _item_expanded(self, item: QTreeWidgetItem) -> None:
        group_type = item.data(0, Qt.ItemDataRole.UserRole)
        if RelationshipGroup.is_group_type(group_type):
            self.view_state.expanded[group_type] = True

    def _item_collapsed(self, item: QTreeWidgetItem) -> None:
        group_type = item.data(0, Qt.ItemDataRole.UserRole)
        if RelationshipGroup.is_group_type(group_type):
            self.view_state.expanded[group_type] = False

    async def write_order(self, order: type[ThreadSort]) -> None:
        """`QtRelationshipSort`'s pick: every sortable group of the snapshot shown takes the
        order, through the shared `RelationshipOrder` write, as Textual's sort writes it."""
        snapshot = self._snapshot
        if snapshot is None:
            raise ValueError("Relationship ordering is not available yet")
        identity = self.thread_identity
        app = self._app
        access = app.coordination_access
        service = await app.preparation.run_thread(lambda: access.observing(identity.root_path))
        try:
            await self.sort.write_relationship_order(
                app.preparation, service, identity, snapshot.sortable_groups, order)
        finally:
            if identity == self.thread_identity:
                self.present()
