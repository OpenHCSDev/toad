"""Shared disclosure, row navigation and keyed tree presentation mechanics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections import Counter
from collections.abc import Iterable
from functools import wraps
from itertools import islice
from contextlib import contextmanager
from time import perf_counter_ns
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.widgets.comms_sidebar import CommsRow
    from agent_comms.comms import Comms
    from toad.comms_root import ObservedCommsService

from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.containers import Vertical, VerticalGroup
from textual.widgets import Static
from textual._activation import PrimaryActivation
from textual.layouts.vertical import VerticalLayout
from textual._measurement import FLOW_HEIGHT, height_dependency

from agent_comms.mro_dispatch import handles
from toad.core.events import SessionSelected, CoordinationObserved, ThreadRowStateChanged
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from agent_comms.ui_model.changes import Changes
from agent_comms.ui_model.sidebar import SidebarModel
from toad.widgets.sidebar_viewport import SidebarHeader
from toad.widgets.side_bar import SideBar


class TargetTreeMember:
    """A navigation control belongs to one required native tree."""

    @property
    def navigation_tree(self) -> TargetTree:
        return self.query_ancestor(TargetTree)

    def action_cursor_up(self) -> None:
        self.navigation_tree.action_cursor_up()

    def action_cursor_down(self) -> None:
        self.navigation_tree.action_cursor_down()


class SidebarDisclosure(PrimaryActivation, Static, can_focus=True):
    BINDINGS = [Binding("enter,space", "toggle", "Expand group", show=False)]
    DEFAULT_CSS = "SidebarDisclosure { width: 2; height: 1; pointer: pointer; }"

    def render(self):
        return "▾" if self.query_ancestor(SidebarGroup).expanded else "▸"

    @property
    def primary_activation(self):
        return self.action_toggle

    def action_toggle(self) -> None:
        self.query_ancestor(SidebarGroup).toggle_members()

    def on_click(self, event) -> None:
        if event.button == 1:
            event.stop()
            self.action_toggle()


class SidebarReaderLayout(VerticalLayout):
    """Native flow, preserving the viewport's reader before placements change."""

    @height_dependency(FLOW_HEIGHT)
    def arrange(self, parent, children, size, greedy=True):
        placements = super().arrange(parent, children, size, greedy)
        parent.query_ancestor(TargetTree).preserve_reader(placements)
        return placements


class RowReconciliation:
    """One sync's model membership and transferable native rows, never a retained cache."""

    def __init__(self, tree):
        demand = Counter(key for key in tree.member_keys if tree.matches(key))
        self.listed = frozenset(demand)
        self.sources = {}
        requests = {}
        for group in tree.navigation_groups:
            wanted = frozenset(group.matching_keys)
            for key in wanted - group.rows.keys():
                requests.setdefault(group, set()).add(key)
            for key in group.rows:
                if key in wanted:
                    demand[key] -= 1
                else:
                    self.sources.setdefault(key, {})[group] = None
        # A thread can have simultaneous views. Keep only the native rows
        # needed by unfilled model slots; a removed duplicate must retire.
        self.sources = {key: dict.fromkeys(islice(groups, max(0, demand[key])))
                        for key, groups in self.sources.items()}
        self.requests = requests

    @staticmethod
    def sync(method):
        @wraps(method)
        def synchronized(view, *args, **kwargs):
            with view.reconciliation_tree.reconcile_members():
                return method(view, *args, **kwargs)
        return synchronized

    def finish(self):
        for group, keys in self.requests.items():
            if any(self.sources.get(key) for key in keys):
                group.sync_members()

    def retains(self, key, group):
        return key in self.listed and group in self.sources.get(key, ())

    def take(self, key, destination):
        sources = self.sources.get(key)
        if not sources:
            return None
        source, _ = sources.popitem()
        row = source.rows.pop(key)
        row.reparent(destination.member_container)
        source.rows_changed()
        return row


class SidebarGroup[RowT: "CommsRow"](VerticalGroup):
    """A common header/disclosure and optional bounded member viewport."""

    navigation_header = False

    DEFAULT_CSS = """
    SidebarGroup { height: auto; }
    SidebarGroup > .group-header { height: 1; }
    SidebarGroup > .group-header > .group-title { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    SidebarGroup > .group-members { height: auto; margin-left: 2; }
    """

    expanded = reactive(False, init=False)

    _rows_pending = False
    """A reconciliation ran out of its step and left rows unmounted."""

    _row_mounting = None
    """The worker mounting pending rows after the following frames."""

    def __init__(self, row, *, expanded: bool, controls=(),
                 disclosure_type=SidebarDisclosure, **kwargs):
        super().__init__(**kwargs)
        self.row = row
        self.rows: dict[str, RowT] = {}
        self.row.add_class("group-title")
        self.disclosure = disclosure_type()
        self.controls = controls
        self.member_container = VerticalGroup(classes="group-members channel-members")
        self.member_container.styles.layout = SidebarReaderLayout()
        self.expanded = expanded

    def compose(self) -> ComposeResult:
        with SidebarHeader(classes="group-header"):
            yield self.disclosure
            yield self.row
            yield from self.controls
        yield self.member_container

    def on_mount(self) -> None:
        self.sync_members()

    def toggle_members(self) -> None:
        self.expanded = not self.expanded
        self.sync_members()

    def sync_members(self, changed: frozenset[str] | None = None) -> None:
        """Specializations reconcile their model-owned member rows; repaint ``changed`` (all if None)."""

    def watch_expanded(self, previous: bool, expanded: bool) -> None:
        self.disclosure.refresh(layout=False)
        if self.is_mounted:
            self.member_container.set_display_constraint("members", self.members_visible)
            self.members_visibility_changed(previous, expanded)
            self.rows_changed()

    def members_visibility_changed(self, previous: bool, expanded: bool) -> None:
        """Specializations preserve existing reader intent across disclosure."""

    @property
    def visible_rows(self):
        """Header and disclosed members in their native order."""
        if not self.accepts_navigation():
            return ()
        header = (self.row,) if self.navigation_header else ()
        members = tuple(self.member_container.children) if self.members_visible else ()
        return (*header, *members)

    @property
    def navigation_rows(self):
        """Native-order destinations, excluding explanatory placeholder widgets."""
        return tuple(row for row in self.visible_rows if row.is_navigation_row())

    def rows_for_target(self, target):
        if not self.accepts_members():
            return ()
        header = (self.row,) if self.navigation_header and self.row.target_name == target else ()
        member = self.rows.get(target)
        return (*header, *((member,) if member is not None and member.is_navigation_row() else ()))

    def accepts_navigation(self) -> bool:
        return self.display and self.accepts_members()

    def accepts_members(self):
        """Native membership is valid until this group starts retirement."""
        return self.is_attached and not self.is_leaving

    def rows_changed(self) -> None:
        """Specializations invalidate navigation after native membership changes."""

    @property
    def member_keys(self):
        """Keys listed by this group's current model, including hidden rows."""
        raise NotImplementedError

    @property
    def reconciliation_tree(self):
        return self.query_ancestor(TargetTree)

    @property
    def matching_keys(self):
        tree = self.reconciliation_tree
        return tuple(key for key in self.member_keys if tree.matches(key))

    @property
    def members_visible(self):
        return self.expanded or bool(self.reconciliation_tree.search)

    @RowReconciliation.sync
    def reconcile_rows(self, create, update, *, changed=None):
        """Retain rows by identity; mount, remove and reorder only what differs.

        Neither a title/status change nor a selection repaint remounts the list.
        New rows are created and mounted in key order (the top of the list
        first) for one layout step's time; the rest follow a step's worth per
        frame, so each frame lays out and paints only the rows just added.
        """
        if not self.accepts_members():
            return ()
        rows = self.rows
        keys = self.matching_keys
        wanted = set(keys)
        tree = self.reconciliation_tree
        self.set_display_constraint("sidebar-search", bool(keys) or not tree.search)
        self.member_container.set_display_constraint("members", self.members_visible)
        self._rows_pending = False
        members = tree.row_reconciliation
        retired = [key for key in rows if key not in wanted and not members.retains(key, self)]
        for key in retired:
            rows.pop(key).retire()
        mounted = []
        deadline = perf_counter_ns() + self.screen.LAYOUT_STEP_NS
        for key in keys:
            current = rows.get(key)
            if current is None:
                current = members.take(key, self)
                if current is None:
                    if not self.members_visible:
                        continue
                    if perf_counter_ns() >= deadline:
                        self._rows_pending = True
                        continue
                    current = create(key)
                rows[key] = current
                update(key, current)
                if not current.is_attached:
                    self.member_container.mount(current)
                mounted.append(current)
                continue
            if changed is None or key in changed or not current.is_attached:
                update(key, current)
        if self._rows_pending and (self._row_mounting is None or self._row_mounting.is_finished):
            self._row_mounting = self.run_worker(self._mount_pending_rows(), group="sidebar-rows")
        ordered = tuple(rows[key] for key in keys if key in rows)
        positions = {row: index for index, row in enumerate(ordered)}
        live = tuple(child for child in self.member_container.children if child in positions)
        reordered = bool(ordered) and live != ordered
        if reordered:
            self.member_container.sort_children(key=lambda child: positions.get(child, len(positions)))
        if retired or mounted or reordered:
            self.rows_changed()
        return ordered

    async def _mount_pending_rows(self) -> None:
        """Mount the rows reconciliation left, a step's worth after each frame."""
        while self._rows_pending and self.accepts_members() and self.members_visible:
            self._rows_pending = False
            refreshed = asyncio.Event()
            self.call_after_refresh(refreshed.set)
            await refreshed.wait()
            # No model change: only the rows created now are painted.
            self.sync_members(frozenset())


class SidebarModelState:
    def shows_model(self) -> bool:
        return False

    def observes(self, observed: ObservedCommsService) -> bool:
        return False

    @property
    def navigation_root(self):
        return None

    def unsubscribe(self, view) -> None:
        pass

    def changes(self, changes):
        return changes

    def apply(self, view, changes) -> None:
        pass

    def member_keys(self):
        return ()

    def mount_source(self):
        return ()

    def channel_row(self, key):
        return None

    def thread_rows(self):
        return {}

    def order_groups(self, view):
        pass

    def update_open_views(self, view):
        pass

    def open_views(self, view):
        return {}

    def welcome_keys(self, section):
        return ()

    def sync_welcome(self, section, changed):
        pass

    def present(self, view):
        view.app.coordination_access.show_sidebar(view, False)
        return self


class Detached(SidebarModelState):
    """No opened service or model belongs to this view."""


@dataclass(frozen=True)
class BoundSidebar(SidebarModelState):
    observed: ObservedCommsService

    @property
    def model(self) -> SidebarModel:
        return self.observed.sidebar

    @property
    def service(self) -> Comms:
        return self.observed.service

    @property
    def navigation_root(self):
        return self.service.root

    def observes(self, observed: ObservedCommsService) -> bool:
        return self.observed is observed

    def unsubscribe(self, view) -> None:
        self.model.channels.unsubscribe(view.channels_changed)
        self.model.threads.unsubscribe(view.threads_changed)

    def present(self, view):
        shown = view.accepts_observation()
        view.app.coordination_access.show_sidebar(view, shown)
        if not shown or self.model.snapshot is None:
            return Behind(self.observed)
        return self.present_current()

    def present_current(self):
        return self


class Current(BoundSidebar):
    def shows_model(self) -> bool:
        return True

    def apply(self, view, changes) -> None:
        if changes:
            view.sync(**changes)

    def member_keys(self):
        return (key for channel in self.model.channels.rows.values() for key in channel.members)

    def mount_source(self):
        return tuple(self.model.channels.rows)

    def channel_row(self, key):
        return self.model.channels.rows.get(key)

    def thread_rows(self):
        return self.model.threads.rows

    def order_groups(self, view):
        view._order_groups()

    def update_open_views(self, view):
        view.open_views = self.open_views(view)

    def open_views(self, view):
        return view._find_open_views(self.model.threads.rows, self.service.root)

    def welcome_keys(self, section):
        return section.keys(self.model)[:section.LIMIT]

    def sync_welcome(self, section, changed):
        section._sync_members(self.model, changed)


class Behind(BoundSidebar):
    def present_current(self):
        return Current(self.observed)

    def changes(self, changes):
        return dict(channels=None, threads=None, reorder=True)


class SidebarModelView(CoreEventReceiver):
    """A widget showing the observed service's sidebar model.

    Core's model is observed only while a view shows it. Changes that arrive
    while this one is hidden are applied in one pass when it shows again.
    """

    def on_mount(self) -> None:
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        service = self.app.coordination_access.observed_service
        if service is not None:
            self.attach(service)

    def on_unmount(self) -> None:
        self.stop_showing()

    def on_show(self) -> None:
        self.present()

    def sidebar_visibility_changed(self) -> None:
        self.present()

    model_state: SidebarModelState = Detached()

    @property
    def navigation_root(self):
        return self.model_state.navigation_root

    def channel_active(self, row) -> bool:
        return self.model_state.shows_model() and row.target.active_in(self.model_state.model.channels)

    def accepts_observation(self) -> bool:
        """Whether this view shows the model now."""
        raise NotImplementedError

    def model_replaced(self) -> None:
        """Retire what showed the previous service's rows."""

    def sync(self, *, channels: frozenset[str] | None, threads: frozenset[str] | None,
             reorder: bool = False) -> None:
        """Apply model changes; ``None`` means every channel or thread changed."""
        raise NotImplementedError

    def unsubscribe(self) -> None:
        self.model_state.unsubscribe(self)
        self.model_state = Detached()

    def stop_showing(self) -> None:
        self.app.coordination_access.show_sidebar(self, False)
        self.unsubscribe()

    def attach(self, service: Comms) -> None:
        """Render ``service``'s shared model; another service's rows are retired first."""
        observed = self.app.coordination_access.observation
        if observed is None or observed.service is not service or self.model_state.observes(observed):
            return  # A newer observed service attaches on its CoordinationObserved.
        self.unsubscribe()
        self.model_state = Behind(observed)
        observed.sidebar.channels.subscribe(self.channels_changed)
        observed.sidebar.threads.subscribe(self.threads_changed)
        self.model_replaced()
        self.present()

    def channels_changed(self, changes: Changes[str]) -> None:
        self.present(
            channels=frozenset((*changes.added, *changes.changed)), threads=frozenset(),
            reorder=bool(changes.added or changes.removed or changes.order is not None))

    def threads_changed(self, changes: Changes[str]) -> None:
        self.present(
            channels=frozenset(),
            threads=frozenset((*changes.added, *changes.removed, *changes.changed)))

    def present(self, **changes) -> None:
        """Publish the next state before it applies pending model changes."""
        previous = self.model_state
        self.model_state = previous.present(self)
        self.model_state.apply(self, previous.changes(changes))

    @handles(CoordinationObserved)
    async def coordination_observed(self, event: CoreEventMessage) -> None:
        service = self.app.coordination_access.observed_service
        if service is not None:
            self.attach(service)

    @handles(ThreadRowStateChanged)
    async def thread_row_state_changed(self, event: CoreEventMessage) -> None:
        """This app's own row state changed: every thread row repaints now, or when shown again."""
        self.present(channels=frozenset(), threads=None)


class SearchFollower:
    def on_mount(self) -> None:
        self.watch(self.query_ancestor(SideBar), "search", self._apply_search, init=True)

    def _apply_search(self, value: str) -> None:
        self.search = value.casefold()
        with self.reconcile_members():
            for group in self.navigation_groups:
                group.sync_members()


class TargetTree(Vertical):
    """Common row keyboard mechanics; specialized trees own data and state."""

    navigation_groups: Iterable[SidebarGroup]
    search = ""

    def matches(self, key: str) -> bool:
        return self.search in key.casefold()

    def preserve_reader(self, placements) -> None:
        """A sidebar viewport may retain its reader across a native relayout."""

    _member_reconciliation = None

    @property
    def member_keys(self):
        return (key for group in self.navigation_groups for key in group.member_keys)

    @property
    def row_reconciliation(self):
        if self._member_reconciliation is None:
            raise RuntimeError("Row reconciliation requires an active member sync")
        return self._member_reconciliation

    @contextmanager
    def reconcile_members(self):
        previous = self._member_reconciliation
        self._member_reconciliation = RowReconciliation(self) if previous is None else previous
        try:
            yield
        finally:
            try:
                if previous is None:
                    self._member_reconciliation.finish()
            finally:
                self._member_reconciliation = previous

    @property
    def reconciliation_tree(self):
        return self

    @property
    def selection_state(self):
        raise NotImplementedError

    def selection_for(self, row):
        raise NotImplementedError

    def accepts_selection(self) -> bool:
        return True

    def row_for(self, selection):
        raise NotImplementedError

    def row_selected(self, row) -> bool:
        return self.selection_for(row) in self.selection_state.selected_targets

    @contextmanager
    def selection_change(self):
        previous = set(self.selection_state.selected_targets)
        try:
            yield
        finally:
            for identity in previous.symmetric_difference(self.selection_state.selected_targets):
                if (row := self.row_for(identity)) is not None:
                    row.refresh_paint()

    def remember_row(self, row) -> None:
        """Navigation establishes a range anchor; it is not bulk selection."""
        rows = self.rows
        if self.accepts_selection() and row in rows:
            with self.selection_change():
                state = self.selection_state
                state.selected = self.selection_for(row)
                state.selected_targets = ()

    def pointer_select(self, row, *, control=False, shift=False, menu=False) -> None:
        if not self.accepts_selection():
            return
        rows = self.rows
        if row not in rows:
            return
        selected = self.selection_for(row)
        state = self.selection_state
        current = state.selected_targets
        if menu and selected in current:
            return
        identities = tuple(self.selection_for(item) for item in rows)
        with self.selection_change():
            if shift and state.selected in identities:
                start, end = sorted((identities.index(state.selected), identities.index(selected)))
                span = identities[start:end + 1]
                state.selected_targets = tuple(dict.fromkeys((*current, *span))) if control else span
            elif control:
                state.selected_targets = (tuple(item for item in current if item != selected)
                                          if selected in current else (*current, selected))
                state.selected = selected
            else:
                state.selected = selected
                state.selected_targets = (selected,)

    def apply_selection(self) -> None:
        with self.selection_change():
            state = self.selection_state
            state.selected_targets = tuple(identity for identity in state.selected_targets
                                           if self.row_for(identity) is not None)

    @property
    def navigation_root(self):
        raise NotImplementedError

    def row_current(self, row) -> bool:
        return row.target_name == self.app.workspace_sessions.visible_target(self.navigation_root)

    def rows_for_target(self, target):
        return tuple(row for group in self.navigation_groups for row in group.rows_for_target(target)) if target is not None else ()

    @property
    def current_rows(self):
        target = self.app.workspace_sessions.visible_target(self.navigation_root)
        return tuple(row for group in self.navigation_groups if group.accepts_navigation()
                     for row in group.rows_for_target(target) if row is group.row or group.members_visible)

    @handles(SessionSelected)
    def session_selected(self, event) -> None:
        workspace = self.app.workspace_sessions
        previous = workspace.target_for_mode(event.event.previous_mode, self.navigation_root)
        current = workspace.visible_target(self.navigation_root)
        for row in set(self.rows_for_target(previous)).symmetric_difference(self.rows_for_target(current)):
            row.paint_current()

    @property
    def rows(self) -> list[CommsRow]:
        return [row for group in self.navigation_groups for row in group.navigation_rows]

    def action_cursor_up(self) -> None:
        self.move_cursor(-1)

    def action_cursor_down(self) -> None:
        self.move_cursor(1)

    def move_cursor(self, direction: int) -> None:
        rows = self.rows
        if rows:
            focused = self.app.focused
            index = rows.index(focused) if focused in rows else -1 if direction > 0 else len(rows)
            row = rows[max(0, min(len(rows) - 1, index + direction))]
            self.focus_row(row)

    def focus_row(self, row) -> None:
        row.scroll_visible(animate=False, immediate=True)
        self.screen.set_focus(row, scroll_visible=False)

    def action_open_selected(self) -> None:
        if (row := self.app.focused) in self.rows:
            row.action_open_selected()
