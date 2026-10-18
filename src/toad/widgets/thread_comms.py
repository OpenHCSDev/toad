"""Owner-scoped right-sidebar communication and explicitly declared work links."""

from __future__ import annotations
from agent_comms.mro_dispatch import handles
from toad.core_event_carrier import CoreEventMessage
from toad.thread_identity import ThreadIdentity, SessionIdentity
from toad.widgets.thread_identity import ShowsThreadIdentity
from toad.core import events as core_events

from toad.navigation_target import NavigationTarget, ThreadTarget

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from agent_comms.display_order import ThreadSort
from agent_comms.route_selection import RouteSelection
from agent_comms.ui_model.sidebar import ThreadRowModel
from textual import on
from textual.binding import Binding
from textual.content import Content
from textual.widgets import Checkbox, Static

from toad.core.input_events import SelectTarget
from toad.widgets.comms_sidebar import CommsRow, ThreadStatusRow
from toad.widgets.message_filter import MessageCategory
from toad.widgets.session_sort import SortControl, ThreadSortForm
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarVisibilityObserver
from toad.widgets.sidebar_tree import SidebarGroup, SidebarModelView, SearchFollower, TargetTree
from agent_comms.relationships import RelationshipEntry, RelationshipGroup, ThreadCommsSnapshot
from toad.widgets.thread_comms_source import RelationshipSource

def entry_target(entry: RelationshipEntry) -> NavigationTarget:
    person = entry.person
    if person is None:
        return NavigationTarget.named(entry.target)
    return ThreadTarget(person.thread.name)


@dataclass
class RelationshipTreeState:
    expanded: dict[type[RelationshipGroup], bool] = field(default_factory=dict)
    selected: tuple[type[RelationshipGroup], tuple[str, str]] | None = None
    selected_targets: tuple[tuple[type[RelationshipGroup], tuple[str, str]], ...] = ()


class RelationshipSort(SortControl[ThreadSort]):
    def __init__(self):
        super().__init__(ThreadSortForm, "relationships")

    def update_groups(self, groups):
        orders = {group.order for group in groups}
        self.update_order(next(iter(orders)) if len(orders) == 1 else None)

    def order_writer(self):
        tree = self.query_ancestor(SideBarCollapsible).query_one(ThreadCommsSidebar)
        identity, generation = tree.thread_view.thread_identity, tree._generation
        snapshot = tree._snapshot
        if snapshot is None:
            raise ValueError("Relationship ordering is not available yet")
        groups = snapshot.sortable_groups

        async def write(order: type[ThreadSort]):
            service = await tree.relationship_source(identity)
            if generation != tree._generation or identity != tree.thread_view.thread_identity:
                return
            try:
                for group in groups:
                    await self.app.preparation.run_thread(service.set_order, identity.thread_name(), type(group), order)
            finally:
                if generation == tree._generation and identity == tree.thread_view.thread_identity:
                    tree.refresh_relationships(force=True)

        return write


class RelationshipRow(ThreadStatusRow):
    BINDINGS = [Binding("ctrl+c", "copy_identity", "Copy name", show=False)]
    available = True
    entry: RelationshipEntry | None = None

    def present(self, entry, model) -> None:
        previous, self.entry = self.entry, entry
        self.available, self.target = entry.available, entry_target(entry)
        if not entry.available:
            self.retire_thread_row()
            self.update(Content(f"? {entry.target}\n  Unavailable · Ctrl+C copies name"), layout=False)
        elif entry.person is not None:
            if model is not None and model.incarnation == entry.person.thread.incarnation:
                self.workers.cancel_group(self, "relationship-row")
                self._show_person(entry, model)
            elif previous != entry:
                self.run_worker(self._present_person(entry), group="relationship-row", exclusive=True)
        elif previous != entry:
            self.set_label(entry.target)
        if entry.person is None:
            self.tooltip = Content(f"{entry.target}\n{entry.detail}") if entry.detail else entry.target

    def _show_person(self, entry, model):
        self.show(model)
        if entry.detail:
            self.tooltip = Content(f"{entry.target}\n{entry.detail}")

    async def _present_person(self, entry):
        model = await self.app.preparation.run_thread(ThreadRowModel.of, entry.person, None)
        if self.entry == entry:
            self._show_person(entry, model)

    def action_copy_identity(self) -> None:
        self.app.copy_to_clipboard(self.target_name)

    def action_open_selected(self) -> None:
        tree = self.query_ancestor(ThreadCommsSidebar)
        tree.remember_row(self)
        if not self.available:
            self.notify("This historical thread is unavailable. Ctrl+C copies its name.",
                        title="Comms")
            return
        tree.request_navigation(self)

    def on_click(self, event) -> None:
        if event.button == 3:
            event.stop()
            self.query_ancestor(ThreadCommsSidebar).show_row_menu(self, event.screen_offset)


class RelationshipRows(SidebarGroup[RelationshipRow]):
    DEFAULT_CSS = """
    RelationshipRows > .group-header > SidebarDisclosure { width: 1; }
    """

    def __init__(self, model: RelationshipGroup, expanded: bool):
        self.model = model
        super().__init__(Static(model.title), expanded=expanded,
                         id=f"relationships-{type(model).declared_name}")

    def members_visibility_changed(self, previous: bool, expanded: bool) -> None:
        state = self.query_ancestor(ThreadCommsSidebar).view_state
        state.expanded[type(self.model)] = expanded

    @property
    def member_keys(self):
        snapshot = self.query_ancestor(ThreadCommsSidebar)._snapshot
        model = snapshot.groups_by_type.get(type(self.model)) if snapshot is not None else None
        return frozenset(entry.target for entry in model.entries) if model is not None else frozenset()

    def present(self, model: RelationshipGroup) -> None:
        previous, self.model = self.model, model
        if previous != model:
            entries = {entry.target: entry for entry in previous.entries}
            changed = frozenset(entry.target for entry in model.entries
                                if entries.get(entry.target) != entry)
            self.sync_members(changed=changed)

    def accepts_members(self) -> bool:
        return (super().accepts_members()
                and self.query_ancestor(ThreadCommsSidebar).accepts_observation())

    def keys_for_threads(self, names: frozenset[str]) -> frozenset[str]:
        return frozenset(entry.target for entry in self.model.entries
                         if entry.person is not None and entry.person.thread.name in names)

    def sync_members(self, changed: frozenset[str] | None = None) -> None:
        """Reconcile member rows from this group's entries and the tree's derived thread rows."""
        if not self.member_container.is_attached or not self.accepts_members():
            return
        tree = self.query_ancestor(ThreadCommsSidebar)
        rows = tree.model.threads.rows
        entries = {entry.target: entry for entry in self.model.entries}
        empty = self.query_one_optional(".relationship-empty")
        if (entries or not self.expanded) and empty is not None:
            empty.remove()
        if self.expanded and not entries and empty is None:
            self.mount(Static(self.model.empty_text, classes="relationship-empty"))

        def create(key):
            entry = entries[key]
            return RelationshipRow(entry_target(entry), entry.target)

        def update(key, row):
            entry = entries[key]
            row.present(entry, rows.get(entry.person.thread.name) if entry.person is not None else None)

        self.reconcile_rows(create, update, changed=changed)
        tree.apply_selection()


class ThreadCommsSidebar(ShowsThreadIdentity, SidebarModelView, SidebarVisibilityObserver, SearchFollower, TargetTree):
    DEFAULT_CSS = """
    ThreadCommsSidebar { height: auto; }
    ThreadCommsSidebar .relationship-context { height: auto; text-wrap: nowrap; text-overflow: clip; color: $text-muted; }
    ThreadCommsSidebar .relationship-empty { height: 1; color: $text-muted; }
    ThreadCommsSidebar > Checkbox { height: 1; border: none; padding: 0; margin: 0; background: transparent; }
    """
    BINDINGS = [("up", "cursor_up", "Previous"), ("down", "cursor_down", "Next"),
                ("enter", "open_selected", "Open")]

    def __init__(self, *, source: RelationshipSource | None = None,
                 states: dict[SessionIdentity, RelationshipTreeState] | None = None):
        super().__init__()
        self._generation = 0
        self._refresh_task = None
        self._revision = None
        self._source = None
        self._filter_view = None
        self._filter_controls: dict[Checkbox, type[MessageCategory]] = {}
        self._snapshot: ThreadCommsSnapshot | None = None
        self._states = states if states is not None else {}
        self.groups: dict[type[RelationshipGroup], RelationshipRows] = {}
        if source is not None:
            self.use_source(source)

    @property
    def view_state(self):
        return self._states.setdefault(self.thread_view.thread_identity, RelationshipTreeState())

    async def relationship_source(self, identity: ThreadIdentity) -> RelationshipSource:
        if self._source is not None:
            return self._source
        access = self.app.coordination_access
        return await self.app.preparation.run_thread(
            lambda: access.require(RouteSelection.capture(identity.root_path())).relationships)

    def use_source(self, source: RelationshipSource) -> None:
        self._source = source
        self._reset_relationships()
        self.refresh_relationships(force=True)

    def compose(self):
        yield Static(self.thread_view.thread_identity.display_thread(), classes="relationship-context", markup=False)
        self._filter_controls.clear()
        for category in MessageCategory.members_with(MessageCategory):
            checkbox = Checkbox(category.label, id=f"filter-{category.declared_name}",
                                classes="message-filter", compact=True)
            self._filter_controls[checkbox] = category
            yield checkbox

    def on_mount(self):
        # Use the left roster's existing observation cadence; no extra timers
        # per group or per mounted thread view.
        self._sync_filter_control()
        self.refresh_relationships()

    def on_show(self):
        if not self.is_attached or not self.screen.is_current:
            return
        # Background tabs retain their source and per-view filter state. Apply
        # the latest owner/selection once they become visible rather than doing
        # seven checkbox queries on every global update in every hidden tab.
        self._sync_filter_control()
        self.refresh_relationships()

    def on_unmount(self):
        self._generation += 1
        if self._refresh_task is not None:
            self._refresh_task.cancel()

    def identity_changed(self, identity: SessionIdentity) -> None:
        self._reset_relationships()
        selected = self.view_state.selected
        self.selected = selected[1] if selected is not None else None
        self.query_one(".relationship-context", Static).update(
            Content(f"For {identity.display_thread()}"), layout=False)
        self.refresh_relationships(force=True)

    def _reset_relationships(self) -> None:
        self._generation += 1
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None
        self._revision = None
        self._snapshot = None
        # Old-root rows are hidden immediately, before a new query can finish.
        for group in self.groups.values():
            group.display = False

    def accepts_observation(self) -> bool:
        identity = self.thread_view.thread_identity
        return (self.service is not None
                and identity.root_path() == self.service.root.resolve())

    def sync(self, *, channels, threads, reorder=False) -> None:
        for group in self.navigation_groups:
            changed = None if threads is None else group.keys_for_threads(threads)
            if changed is None or changed:
                group.sync_members(changed=changed)

    @handles(core_events.OpenTabsChanged, core_events.SessionSelected, core_events.CoordinationObserved)
    async def _observed(self, event: CoreEventMessage) -> None:
        if not self.is_attached or not self.screen.is_current:
            return
        if not self.query_ancestor(SideBar).presentation_visible:
            return
        self._sync_filter_control()
        self.refresh_relationships()

    def _sync_filter_control(self):
        from toad.screens.session_view import SessionView
        from toad.widgets.conversation import Conversation

        view = self.query_ancestor(SessionView).query_one_optional(Conversation)
        checkboxes = tuple(self.query(Checkbox))
        for checkbox in checkboxes:
            checkbox.display = view is not None
        if view is not None:
            if self._filter_view is not view:
                self._filter_view = view
                self.watch(view, "visible_categories", self._sync_filter_control)
            with self.prevent(Checkbox.Changed):
                for checkbox in checkboxes:
                    checkbox.value = self._filter_controls[checkbox] in view.visible_categories

    @on(Checkbox.Changed, ".message-filter")
    def filter_changed(self, event):
        event.stop()
        if self._filter_view is not None:
            category = self._filter_controls.get(event.checkbox)
            if category is not None:
                selected = self._filter_view.visible_categories
                self._filter_view.visible_categories = (
                    selected | {category} if event.value else selected - {category}
                )

    def _visible(self):
        return (self.is_attached and self.screen.is_current
                and self in self.screen._compositor.visible_widgets
                and not self.query_ancestor(SideBarCollapsible).collapsed)

    def refresh_relationships(self, *, force=False):
        if force:
            self._revision = None
        if not self.is_mounted or not self._visible():
            return
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._refresh(self._generation))

    async def _refresh(self, generation):
        await self.thread_view.thread_identity.inspect_owner(
            lambda identity: self._refresh_owner(identity, generation),
            lambda text: self.query_one(".relationship-context", Static).update(Content(text), layout=False))

    async def _refresh_owner(self, identity: ThreadIdentity, generation):
        try:
            service = await self.relationship_source(identity)
            if generation != self._generation or not self.is_attached:
                return
            owner = identity.thread_name()
            revision = await asyncio.to_thread(service.revision)
            if revision == self._revision:
                return
            snapshot = await asyncio.to_thread(service.snapshot, owner)
            # Visibility admits new reads; parking does not revoke work already
            # owned by this retained panel. Identity changes and unmount do.
            if generation != self._generation or not self.is_attached:
                return
            if snapshot.owner != owner or Path(snapshot.root).resolve() != identity.root_path():
                raise ValueError("Relationship snapshot does not match this thread and wire")
            if self._snapshot is None and self.groups:
                # Owner/root replacement is a new source lifetime. Do not
                # adopt same-named native rows from the hidden previous tree.
                await self.remove_children(list(self.groups.values()))
                self.groups.clear()
                if generation != self._generation or not self.is_attached:
                    return
            models = snapshot.groups_by_type
            absent = self.groups.keys() - models.keys()
            self._snapshot, self._revision = snapshot, revision
            context = self.query_one(".relationship-context", Static)
            context.update(Content.assemble((f"For @{snapshot.owner}", "bold"),
                " · recent window" if snapshot.history_limited else ""), layout=False)
            context.tooltip = snapshot.incoming_basis + f"\nLatest {snapshot.history_messages} wire messages"
            control = self.query_ancestor(SideBarCollapsible).query_one_optional(RelationshipSort)
            if control is not None:
                control.update_groups(snapshot.sortable_groups)
            with self.reconcile_members():
                for identity, model in models.items():
                    group = self.groups.get(identity)
                    if group is None:
                        # A new group reconciles once composed (on_mount).
                        group = self.groups[identity] = RelationshipRows(
                            model, self.view_state.expanded.get(identity, True))
                        await self.mount(group)
                        if generation != self._generation or not self.is_attached:
                            return
                    group.display = True
                    group.expanded = self.view_state.expanded.get(identity, True)
                    group.present(model)
            if absent:
                await self.remove_children([self.groups.pop(key) for key in absent])
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError) as error:
            if generation == self._generation and self.is_attached:
                context = self.query_one(".relationship-context", Static)
                context.update(Content("Comms unavailable"), layout=False)
                context.tooltip = str(error)

    @property
    def member_keys(self):
        return (entry.target for model in self._snapshot.groups for entry in model.entries) if self._snapshot is not None else ()

    @property
    def navigation_groups(self):
        return self.groups.values()

    @property
    def selection_state(self):
        return self.view_state

    def selection_for(self, row):
        return type(row.query_ancestor(RelationshipRows).model), row.entry.identity

    def row_for(self, selection):
        group = self.groups.get(selection[0])
        row = group.rows.get(selection[1][1]) if group is not None and group.members_visible and group.accepts_navigation() else None
        return row if row is not None and row.entry.identity == selection[1] else None

    @property
    def navigation_root(self):
        return self.thread_view.thread_identity.root_path()

    def open_target(self, target: NavigationTarget):
        identity = self.thread_view.thread_identity
        if identity.root_path() != self.app.coordination_access.service.root.resolve():
            self.notify("This view uses a different wire; open its matching connection to navigate.",
                        title="Comms", severity="warning")
            return
        self.publish_core(SelectTarget(target))

    def request_navigation(self, row, *, entry=None, generation=None):
        if not row.is_attached:
            return
        expected = row.entry if entry is None else entry
        observed_generation = self._generation if generation is None else generation
        group = type(row.query_ancestor(RelationshipRows).model)
        self.run_worker(self._navigate_current(group, expected, observed_generation))

    async def _navigate_current(self, group_key, expected, generation):
        if generation != self._generation or not expected.available:
            return
        identity = self.thread_view.thread_identity
        try:
            service = await self.relationship_source(identity)
            snapshot = await asyncio.to_thread(service.snapshot, identity.thread_name())
            if (generation != self._generation or not self.is_attached
                    or not self.screen.is_current):
                return
            if snapshot.owner != identity.thread_name() or Path(snapshot.root).resolve() != identity.root_path():
                raise ValueError("Relationship snapshot does not match this thread and wire")
            current = snapshot.current_entry(group_key, expected)
            if current is None:
                self.notify("This relationship changed; refresh the list before opening it.", title="Comms")
                self.refresh_relationships(force=True)
                return
            self.open_target(entry_target(current))
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Comms target unavailable", severity="error")

    def show_row_menu(self, row, offset):
        from toad.widgets.comms_menu import show_target_menu

        target, entry, generation = row.target_name, row.entry, self._generation

        def open_selected():
            # Menus hold an identity, not a row index that live sorting or
            # root/owner rebinding can change before the user activates it.
            if generation == self._generation and row.is_attached and row.available:
                self.request_navigation(row, entry=entry, generation=generation)

        items = [("open", "Open")] if row.available else []
        items.append(("copy", "Copy name"))
        show_target_menu(self.screen, offset, target, items,
                         {"open": open_selected,
                          "copy": lambda: self.app.copy_to_clipboard(target)})
