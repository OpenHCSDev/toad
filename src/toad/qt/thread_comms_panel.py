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
from abc import ABC
from dataclasses import dataclass
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
from toad.thread_sidebar_declarations import CommsSidebarPanel
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


class RelationshipRowItem(ABC):
    """Tree row item queried for its relationship entry."""

    def _row_entry(self) -> tuple[object, RelationshipEntry] | None:
        pass

    @classmethod
    def from_optional(cls, value: QTreeWidgetItem | None) -> RelationshipRowItem:
        return AbsentRelationshipRowItem() if value is None else HeldRelationshipRowItem(value)


@dataclass(frozen=True)
class AbsentRelationshipRowItem(RelationshipRowItem):
    """Absent `RelationshipRowItem` carrying no value."""


@dataclass(frozen=True)
class HeldRelationshipRowItem(RelationshipRowItem):
    """Held `RelationshipRowItem` carrying its present value."""

    value: QTreeWidgetItem

    def _row_entry(self) -> tuple[object, RelationshipEntry] | None:
        if self.value.data(0, _ENTRY) is None:
            return None
        return (self.value.parent().data(0, Qt.ItemDataRole.UserRole), self.value.data(0, _ENTRY))


class QtThreadCommsPanel(LineMenuTree, RelationshipPanel, SessionPanel, QWidget, metaclass=PyQtWidgetMeta):
    panel_type = CommsSidebarPanel

    """Renders a thread's relationship rows as a Qt tree: top-level items per
    `RelationshipGroup`, children per `RelationshipEntry`. The snapshot is fetched off the
    UI thread through `app.preparation.run_thread`, as Textual's `ThreadCommsSidebar` does.
    State (group-expansion, selection) is kept per `SessionIdentity` in the shared
    `RelationshipTreeState` so a reopened tab restores its prior view."""

    def __init__(self, app, search: SidebarFilter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        # The thread sidebar's search narrows the relationship rows, as Textual's
        # `ThreadCommsSidebar` follows its sidebar's search (`SearchFollower`).
        self._search = search
        search.subscribe(lambda _text: self._reapply_search())
        self._states: dict[SessionIdentity, RelationshipTreeState] = {}
        self._snapshot: ThreadCommsSnapshot | None = None
        self._snapshot_identity: SessionIdentity | None = None
        self._revision: object = None
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

    def _reapply_search(self) -> None:
        if self._snapshot is not None and self._snapshot_identity == self.thread_identity:
            self._apply(self._snapshot)
        else:
            self.present()

    def present(self, *, force: bool = False) -> None:
        if force:
            self._revision = None
        self._sync_checks()
        asyncio.ensure_future(self._refresh())

    async def _refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.current_task()
        try:
            await self.thread_identity.inspect_owner(
                self._refresh_owner,
                self.show_source_unavailable,
            )
        finally:
            self._refresh_task = None

    async def _refresh_owner(self, identity) -> None:
        app = self._app
        service = await self.observed_source(app.coordination_access, app.preparation, identity.root_path)
        if service is None or identity != self.thread_identity:
            return
        revision = await app.preparation.run_thread(service.wire_revision)
        if identity == self._snapshot_identity and revision == self._revision:
            return
        snapshot = await app.preparation.run_thread(service.relationships, identity.thread_name())
        if identity != self.thread_identity:
            return
        self._snapshot_identity = identity
        self._revision = revision
        self._apply(snapshot)

    def show_source_unavailable(self, text: str) -> None:
        self._snapshot = None
        self._snapshot_identity = None
        self._revision = None
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

    def _row_entry(self, item: RelationshipRowItem) -> tuple[object, RelationshipEntry] | None:
        """The group and relationship an entry row shows; a group or "none" line shows none."""
        return item._row_entry()

    def _item_clicked(self, item: QTreeWidgetItem) -> None:
        shown = self._row_entry(HeldRelationshipRowItem(item))
        if shown is not None and shown[1].available:
            asyncio.ensure_future(
                self.open_current_relationship(
                    self._app.coordination_access, self._app.preparation, *shown
                )
            )

    def _offer_row_menu(self, point) -> None:
        """The relationship's own menu (`RelationshipLine.menu_entries`) for the row under
        ``point`` (viewport coordinates), in the window's menu panel; a group line has none."""
        item = self._tree.itemAt(point)
        if self._row_entry(RelationshipRowItem.from_optional(item)) is None:
            return
        asyncio.ensure_future(self._offer_read(item))

    async def _offer_read(self, item: QtRelationshipItem) -> None:
        entries = await item.menu_entries()
        self._app.offer_entries(entries)

    def relationship_opener(self, line: QtRelationshipItem):
        """Open reads the list again first (`open_current_relationship`), as Textual does."""
        return lambda: asyncio.ensure_future(
            self.open_current_relationship(
                self._app.coordination_access, self._app.preparation, line.group, line.entry
            )
        )

    def copy_name(self, name: str) -> None:
        self._app.copy_to_clipboard(name)

    def notify_comms_warning(self, message: str) -> None:
        self._app.show_warning(message, "Comms")

    def refresh_after_changed_entry(self) -> None:
        self.present(force=True)

    def select_relationship_target(self, target) -> None:
        self._app.open_target(target)

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
                self.present(force=True)
