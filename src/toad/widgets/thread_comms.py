"""Owner-scoped right-sidebar communication and explicitly declared work links."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from agent_comms import ThreadSort
from textual import on
from textual.binding import Binding
from textual.content import Content
from textual.widgets import Checkbox, Static

from toad.widgets.comms_sidebar import CommsRow, CommsSidebar, SelectTarget
from toad.widgets.activity_spinner import FRAMES
from toad.widgets.message_filter import MESSAGE_CATEGORIES, MESSAGE_LABELS, MessageCategory
from toad.widgets.session_sort import SortControl
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarVisibilityObserver
from toad.widgets.sidebar_tree import SidebarGroup, TargetTree
from toad.widgets.thread_comms_model import RelationshipGroup, RelationshipSource, ThreadCommsSnapshot


def _update_content(widget: Static, content: Content) -> None:
    """Retain identical text and spans; polling itself is not a paint change."""
    previous = widget.content
    if not isinstance(previous, Content) or not previous.is_same(content):
        widget.update(content, layout=False)


@dataclass
class RelationshipTreeState:
    expanded: dict[str, bool] = field(default_factory=dict)
    scroll: dict[str, float] = field(default_factory=dict)
    selected: tuple[str, str] | None = None


class RelationshipSort(SortControl[ThreadSort]):
    GROUPS = ("children", "collaborating")

    def __init__(self):
        self._mixed = True
        super().__init__(ThreadSort.CREATED, "children and collaborators")

    @property
    def selected_order(self):
        return None if self._mixed else self.order

    def _update_label(self) -> None:
        if self._mixed:
            self._set_label("Sort ▾", "Sort children and collaborators (currently different orders)")
        else:
            super()._update_label()

    def update_groups(self, groups):
        orders = {group.order for group in groups if group.key in self.GROUPS}
        self._mixed = len(orders) != 1
        if not self._mixed:
            self.order = next(iter(orders))
        self._update_label()

    async def persist_order(self, order: ThreadSort) -> ThreadSort:
        tree = self.query_ancestor(SideBarCollapsible).query_one(ThreadCommsSidebar)
        service, owner = tree.service, tree.owner
        try:
            for group in self.GROUPS:
                await asyncio.to_thread(service.set_order, owner, group, order)
        finally:
            tree.refresh_relationships(force=True)
        self._mixed = False
        return order


class RelationshipRow(CommsRow):
    BINDINGS = [Binding("ctrl+c", "copy_identity", "Copy name", show=False)]
    available = True

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
        else:
            super().on_click(event)


class RelationshipRows(SidebarGroup):
    DEFAULT_CSS = """
    RelationshipRows > .group-header > SidebarDisclosure { width: 1; }
    """

    EMPTY = {"inbound": "No recent inbound", "outbound": "No recent outbound",
             "parent": "Not forked", "children": "No children",
             "collaborating": "No active collaborations"}

    def __init__(self, model: RelationshipGroup, expanded: bool):
        self.model = model
        self.rows: dict[tuple[str, str], RelationshipRow] = {}
        self._sync_lock = asyncio.Lock()
        super().__init__(Static(model.title), expanded=expanded, scrollable=False,
                         id=f"relationships-{model.key}")

    async def update_group(self, model: RelationshipGroup) -> None:
        self.model = model
        await self._sync_members()

    async def _sync_members(self) -> None:
        if not self.is_mounted:
            return
        async with self._sync_lock:
            tree = self.query_ancestor(ThreadCommsSidebar)
            state = tree.view_state
            container = self.member_container
            if not self.expanded:
                if container.display:
                    state.scroll[self.model.key] = container.scroll_y
                container.display = False
                return
            was_hidden = not container.display
            container.display = True
            entries = {(entry.kind, entry.target): entry for entry in self.model.entries}
            empty = container.query_one_optional(".relationship-empty")
            if entries and empty is not None:
                await empty.remove()
            if not entries and empty is None:
                await container.mount(Static(self.EMPTY[self.model.key], classes="relationship-empty"))
            # Keep the top visible row stable when newer entries reorder a
            # scrolled list. Identity, rather than list index, owns selection.
            anchor = next((row for row in container.children
                           if isinstance(row, RelationshipRow) and row.region.bottom > container.content_region.y), None)
            old_scroll = container.scroll_y
            previous_order = tuple(container.children)

            def create(key):
                entry = entries[key]
                kind = (CommsSidebar._person_kind(entry.person) if entry.person else entry.kind)
                return RelationshipRow(kind, entry.target, entry.target)

            def update(key, row):
                entry = entries[key]
                row.entry = entry
                row.available = entry.available
                row.kind = CommsSidebar._person_kind(entry.person) if entry.person else entry.kind
                if not entry.available:
                    row.remove_class("-busy", "-unread", "-current")
                    row.add_class("-wire-thread")
                    row._thread_signature = None
                    _update_content(row, Content(f"? {entry.target}\n  Unavailable · Ctrl+C copies name"))
                elif entry.person is not None:
                    row.update_thread(entry.person, unread=tree.unread(entry.target, row.kind),
                                      action_status=tree.app.pending_thread_actions.get(entry.target))
                else:
                    row.set_label(entry.target)
                    row.tooltip = entry.target
                if entry.detail:
                    row.tooltip = Content(f"{entry.target}\n{entry.detail}")
                row.set_class(state.selected == (self.model.key, entry.target), "-selected")

            ordered = await self.reconcile_rows(entries, self.rows, create, update)
            if ordered != previous_order:
                if old_scroll > 0 and anchor in ordered:
                    new_y = sum(2 if row.has_class("-wire-thread") else 1
                                for row in ordered[:ordered.index(anchor)])
                    container.scroll_to(y=new_y, animate=False, immediate=True)
            if was_hidden:
                container.scroll_to(y=state.scroll.get(self.model.key, 0), animate=False)


class ThreadCommsSidebar(SidebarVisibilityObserver, TargetTree):
    DEFAULT_CSS = """
    ThreadCommsSidebar { height: auto; }
    ThreadCommsSidebar .relationship-context { height: auto; text-wrap: nowrap; text-overflow: clip; color: $text-muted; }
    ThreadCommsSidebar .relationship-empty { height: 1; color: $text-muted; }
    ThreadCommsSidebar > Checkbox { height: 1; border: none; padding: 0; margin: 0; background: transparent; }
    """
    BINDINGS = [("up", "cursor_up", "Previous"), ("down", "cursor_down", "Next"),
                ("enter", "open_selected", "Open")]

    def __init__(self, owner: str, *, wire_root: str | None = None,
                 source: RelationshipSource | None = None, live: bool = False):
        super().__init__()
        self.owner = owner
        self.wire_root = wire_root
        self.selected = ""
        self._cursor = 0
        self._generation = 0
        self._refresh_task = None
        self._revision = None
        self._source = source
        self._live = live
        self._filter_view = None
        self._filter_controls: dict[Checkbox, MessageCategory] = {}
        self._snapshot: ThreadCommsSnapshot | None = None
        self._states: dict[tuple[str | None, str], RelationshipTreeState] = {}
        self.groups: dict[str, RelationshipRows] = {}
        self._horizontal_width = 0
        self._spinner_phase = 0
        self._spinner_timer = None

    @property
    def view_state(self):
        return self._states.setdefault((self.wire_root, self.owner), RelationshipTreeState())

    @property
    def service(self):
        if self._source is None:
            raise ValueError("Relationship source is not connected")
        return self._source

    def compose(self):
        yield Static("Connecting…", classes="relationship-context", markup=False)
        self._filter_controls.clear()
        for category in MESSAGE_CATEGORIES:
            checkbox = Checkbox(MESSAGE_LABELS[category], id=f"filter-{category.value}",
                                classes="message-filter", compact=True)
            self._filter_controls[checkbox] = category
            yield checkbox

    def on_mount(self):
        self._spinner_timer = self.set_interval(.18, self._animate_busy, pause=True)
        # Use the left roster's existing observation cadence; no extra timers
        # per group or per mounted thread view.
        self.app.coordination_observed.subscribe(self, self._observed)
        self.app.open_tabs_changed.subscribe(self, self._observed)
        self.app.mode_change_signal.subscribe(self, self._observed)
        self.app.thread_actions_changed.subscribe(self, self._observed)
        if self._live:
            self._bind_screen_identity()
        self._sync_filter_control()
        self.refresh_relationships()

    def _sync_spinner(self) -> None:
        if self._spinner_timer is None:
            return
        sidebar = self.query_ancestor(SideBar)
        if (self.screen.is_active and not sidebar.collapsed
                and any(row.has_class("-busy") for group in self.groups.values() for row in group.rows.values())):
            self._spinner_timer.resume()
        else:
            self._spinner_timer.pause()

    def sidebar_visibility_changed(self) -> None:
        self._sync_spinner()

    def _animate_busy(self) -> None:
        if not self.screen.is_active:
            self._sync_spinner()
            return
        self._spinner_phase = (self._spinner_phase + 1) % len(FRAMES)
        for group in self.groups.values():
            for row in group.rows.values():
                if row.has_class("-busy"):
                    row.advance_spinner(self._spinner_phase)

    def on_show(self):
        if not self.is_attached or self.screen is not self.app.screen:
            return
        # Background tabs retain their source and per-view filter state. Apply
        # the latest owner/selection once they become visible rather than doing
        # seven checkbox queries on every global update in every hidden tab.
        if self._live:
            self._bind_screen_identity()
        self._sync_filter_control()
        self.refresh_relationships()

    def on_unmount(self):
        self._generation += 1
        if self._refresh_task is not None:
            self._refresh_task.cancel()

    def set_identity(self, owner: str, wire_root: str | None, *,
                     source: RelationshipSource | None = None):
        if self._live and source is None:
            if (owner, wire_root) == (self.owner, self.wire_root) and self._source is not None:
                return
            if wire_root is not None:
                from toad.widgets.thread_comms_source import WireRelationshipSource

                source = WireRelationshipSource(wire_root, self.app.coordination_wire)
        if (owner, wire_root) == (self.owner, self.wire_root) and source is self._source:
            return
        for group in self.groups.values():
            self.view_state.scroll[group.model.key] = group.member_container.scroll_y
        self._generation += 1
        self.owner, self.wire_root = owner, wire_root
        self._revision = None
        self._source = source
        self._snapshot = None
        # Old-root rows are hidden immediately, before a new query can finish.
        for group in self.groups.values():
            group.display = False
        self.refresh_relationships(force=True)

    def _observed(self, _value):
        if not self.is_attached or self.screen is not self.app.screen:
            return
        if self._live:
            self._bind_screen_identity()
        self._sync_filter_control()
        self.refresh_relationships()

    def _sync_filter_control(self):
        from toad.screens.main import MainScreen
        from toad.widgets.conversation import Conversation

        view = self.screen.query_one_optional(Conversation) if isinstance(self.screen, MainScreen) else None
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

    def _bind_screen_identity(self):
        from toad.screens.main import MainScreen
        from toad.screens.comms import CommsScreen

        if isinstance(self.screen, MainScreen):
            self.set_identity(self.screen._comms_thread, self.screen._coordination_root)
        elif isinstance(self.screen, CommsScreen):
            self.set_identity(self.screen.me, self.screen.recovery_root)

    def _visible(self):
        return (self.is_attached and self.screen is self.app.screen
                and self in self.screen._compositor.visible_widgets
                and not self.query_ancestor(SideBarCollapsible).collapsed)

    def refresh_relationships(self, *, force=False):
        if force:
            self._revision = None
        if not self.is_mounted or not self._visible():
            return
        context = self.query_one(".relationship-context", Static)
        if not self.owner or not self.wire_root:
            _update_content(context, Content("Waiting for thread identity"))
            return
        if self._source is None:
            _update_content(context, Content("Relationship source not connected"))
            return
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._refresh(self._generation))

    async def _refresh(self, generation):
        try:
            service, owner = self.service, self.owner
            revision = await asyncio.to_thread(service.revision)
            if revision == self._revision:
                return
            snapshot = await asyncio.to_thread(service.snapshot, owner)
            if generation != self._generation or not self._visible():
                return
            if snapshot.owner != owner or Path(snapshot.root).resolve() != Path(self.wire_root).resolve():
                raise ValueError("Relationship snapshot does not match this thread and wire")
            with self.app.batch_update():
                context = self.query_one(".relationship-context", Static)
                _update_content(context, Content.assemble((f"For @{snapshot.owner}", "bold"),
                    " · recent window" if snapshot.history_limited else ""))
                context.tooltip = snapshot.incoming_basis + f"\nLatest {snapshot.history_messages} wire messages"
                control = self.query_ancestor(SideBarCollapsible).query_one_optional(RelationshipSort)
                if control is not None:
                    control.update_groups(snapshot.groups)
                for model in snapshot.groups:
                    if generation != self._generation:
                        return
                    group = self.groups.get(model.key)
                    if group is None:
                        group = self.groups[model.key] = RelationshipRows(
                            model, self.view_state.expanded.get(model.key, True))
                        await self.mount(group)
                        if generation != self._generation:
                            group.display = False
                            return
                    group.display = True
                    group.expanded = self.view_state.expanded.get(model.key, True)
                    glyph = "▾" if group.expanded else "▸"
                    if group.disclosure.content != glyph:
                        group.disclosure.update(glyph, layout=False)
                    await group.update_group(model)
                    if generation != self._generation:
                        group.display = False
                        return
                if generation != self._generation:
                    return
                widest = Content(f"For @{snapshot.owner} · recent window").cell_length + 4
                for model in snapshot.groups:
                    for entry in model.entries:
                        widest = max(widest, Content(entry.target).cell_length + 8)
                        if entry.person is not None:
                            widest = max(widest,
                                         Content(entry.person.presentation.label).cell_length + 8,
                                         Content(entry.person.presentation.summary).cell_length + 8)
                        if entry.detail:
                            widest = max(widest, Content(entry.detail).cell_length + 8)
                panel = self.query_ancestor(SideBarCollapsible)
                width = min(widest, 512)
                if width != self._horizontal_width:
                    self._horizontal_width = width
                    panel.styles.min_width = width
                self._snapshot, self._revision = snapshot, revision
                self._sync_spinner()
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError) as error:
            if generation == self._generation and self.is_attached:
                context = self.query_one(".relationship-context", Static)
                _update_content(context, Content("Comms unavailable"))
                context.tooltip = str(error)

    @on(SidebarGroup.Toggled)
    def group_toggled(self, event):
        if isinstance(event.group, RelationshipRows):
            event.stop()
            self.view_state.expanded[event.group.model.key] = event.group.expanded

    def _ordered_rows(self):
        return [row for group in self.groups.values() if group.expanded and group.display
                for row in group.member_container.children if isinstance(row, RelationshipRow)]

    def remember_row(self, row):
        group = row.query_ancestor(RelationshipRows)
        self.view_state.selected = group.model.key, row.target_name
        self.selected = row.target_name
        for visible in self._ordered_rows():
            visible.set_class(visible is row, "-selected")

    def unread(self, name, kind):
        snapshot = self.app._sidebar_snapshot
        if (snapshot is None or self.wire_root is None
                or Path(self.wire_root).resolve() != self.app.coordination_wire.root.resolve()):
            return 0
        return (snapshot.thread_unread if kind == "thread" else snapshot.unread).get(name, 0)

    def open_target(self, target: str, kind: str):
        if self.wire_root is None or Path(self.wire_root).resolve() != self.app.coordination_wire.root.resolve():
            self.notify("This view uses a different wire; open its matching connection to navigate.",
                        title="Comms", severity="warning")
            return
        self.post_message(SelectTarget(target, kind))

    def request_navigation(self, row, *, entry=None, generation=None):
        if not row.is_attached:
            return
        expected = row.entry if entry is None else entry
        observed_generation = self._generation if generation is None else generation
        group = row.query_ancestor(RelationshipRows).model.key
        self.run_worker(self._navigate_current(group, expected, observed_generation))

    async def _navigate_current(self, group_key, expected, generation):
        if generation != self._generation or not expected.available:
            return
        owner, service = self.owner, self.service
        try:
            snapshot = await asyncio.to_thread(service.snapshot, owner)
            if (generation != self._generation or not self.is_attached
                    or self.screen is not self.app.screen):
                return
            if snapshot.owner != owner or Path(snapshot.root).resolve() != Path(self.wire_root).resolve():
                raise ValueError("Relationship snapshot does not match this thread and wire")
            current = next((entry for group in snapshot.groups if group.key == group_key
                            for entry in group.entries
                            if (entry.kind, entry.target) == (expected.kind, expected.target)), None)
            same_incarnation = (expected.person is None or
                (current is not None and current.person is not None and
                 current.person.thread.created_at == expected.person.thread.created_at))
            if current is None or not current.available or not same_incarnation:
                self.notify("This relationship changed; refresh the list before opening it.", title="Comms")
                self.refresh_relationships(force=True)
                return
            kind = CommsSidebar._person_kind(current.person) if current.person else current.kind
            self.open_target(current.target, kind)
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
