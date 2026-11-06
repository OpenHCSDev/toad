"""Shared disclosure, row navigation and keyed tree presentation mechanics."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from itertools import islice
from time import perf_counter_ns
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.events import Click
    from textual.layout import WidgetPlacement

    from toad.app import ToadApp
    from toad.comms_root import FailedObservation, Observing
    from toad.navigation_target import NavigationTarget
    from toad.widgets.channel_activity import ChannelActivity
    from toad.widgets.comms_sidebar import CommsRow, CommsSidebar, ListedRow
    from toad.widgets.thread_comms import RelationshipRows

from agent_comms.display_order import ThreadSort
from metaclass_registry.mro_dispatch import handles
from agent_comms.ui_model.changes import Changes
from agent_comms.ui_model.sidebar import ChannelRowModel, SidebarModel
from agent_comms.ui_model.unread import UnobservedUnread
from toad.widget_actions import Activates
from textual._measurement import FLOW_HEIGHT, height_dependency
from textual.app import ComposeResult
from textual.navigation import CursorCommand, MovesHorizontalCursor
from toad.widget_actions import HiddenActions, StepsVerticalCursor, VisibleActions
from textual.containers import Vertical, VerticalGroup
from textual import events
from textual._activation import CallbackTarget
from rich.style import Style
from textual.content import Content
from textual.strip import Strip
from textual.geometry import Offset, Region, Size
from textual.layouts.vertical import VerticalLayout
from textual.reactive import reactive
from textual.widget import Widget
from textual.worker import Worker
from textual.widgets import Static

from toad.core.events import (
    CoordinationObserved,
    SessionSelected,
    ThreadRowStateChanged,
)
from toad.core_event_carrier import CoreEventReceiver
from toad.native_style import PointerCursor
from toad.no_worker import NoWorker
from toad.widgets.side_bar import SideBar


class UnpaintedChannel(ChannelRowModel):
    """An unobserved channel has no painted fields or known members."""

    def __init__(self, name: str) -> None:
        super().__init__(
            name, "", "", UnobservedUnread(), False, (), frozenset(), ThreadSort
        )


class TargetTreeMember(HiddenActions):
    """A navigation control belongs to one required native tree."""

    @property
    def navigation_tree(self) -> TargetTree:
        return self.query_ancestor(TargetTree)

class HeaderSegment(ABC):
    """One stretch of a group's header line, painted from its group."""

    @abstractmethod
    def content(self, group: SidebarGroup) -> Content: ...

    async def click(self, row: GroupHeaderLine, event: events.Click) -> None:
        """A passive stretch leaves the click to the row's own handler."""

    def activation_targets(self, row: GroupHeaderLine, region: Region):
        """A hint over a passive stretch reaches the row's own effect."""
        return row.row_activation_targets(region)


class ActiveSegment(HeaderSegment):
    """A stretch whose click is its own action, not the row's."""

    def activation_targets(self, row: GroupHeaderLine, region: Region):
        return (CallbackTarget(row, row.segment_region(self), self.activate, arguments=(row,)),)

    async def click(self, row: GroupHeaderLine, event: events.Click) -> None:
        if event.button == 1:
            event.stop()
            event.prevent_default()
            await self.activate(row)

    @abstractmethod
    async def activate(self, row: GroupHeaderLine) -> None: ...


class Disclosure(ActiveSegment):
    """The group's expanded/collapsed arrow; a click toggles its members."""

    def __init__(self, width: int) -> None:
        self.width = width

    def content(self, group: SidebarGroup) -> Content:
        return Content(("▾" if group.expanded else "▸").ljust(self.width))

    async def activate(self, row: GroupHeaderLine) -> None:
        row.header_group.toggle_members()


class TitleSegment(HeaderSegment):
    """The row's own title, truncated into the room the other segments leave."""

    def content(self, group: SidebarGroup) -> Content:
        return group.row.content


TITLE = TitleSegment()


class GroupHeaderLine(PointerCursor, Static):
    """A group's whole header line as one widget: its segments around the row's title.

    The line is the group's row, so a disclosure, a badge or a control costs a
    painted stretch, not a mounted widget.
    """

    content: Content
    _segment_ends: tuple[tuple[int, HeaderSegment], ...] = ()

    @property
    def header_group(self) -> SidebarGroup:
        return self.query_ancestor(SidebarGroup)

    def render(self) -> Content:
        group = self.header_group
        leading = [(segment, segment.content(group)) for segment in group.leading_segments]
        trailing = [(segment, segment.content(group)) for segment in group.trailing_segments]
        fixed = sum(content.cell_length for _, content in (*leading, *trailing))
        title = self.content.truncate(max(0, self.size.width - fixed), ellipsis=True, pad=True)
        pieces = (*leading, (TITLE, title), *trailing)
        ends, end = [], 0
        for segment, content in pieces:
            end += content.cell_length
            ends.append((end, segment))
        self._segment_ends = tuple(ends)
        return Content.assemble(*(content for _, content in pieces))

    def segment_at(self, x: int) -> HeaderSegment:
        return next((segment for end, segment in self._segment_ends if x < end), TITLE)

    def segment_span(self, segment: HeaderSegment) -> tuple[int, int]:
        start = 0
        for end, candidate in self._segment_ends:
            if candidate is segment:
                return start, end
            start = end
        return 0, self.size.width

    def segment_region(self, segment: HeaderSegment) -> Region:
        start, end = self.segment_span(segment)
        content = self.content_region
        return Region(content.x + start, content.y, end - start, 1)

    def emphasize(self, line: Strip, style: Style) -> Strip:
        """Only the title carries the row's emphasis; the arrow and controls keep their ink."""
        start, end = self.segment_span(TITLE)
        return Strip.join((line.crop(0, start), line.crop(start, end).apply_style(style),
                           line.crop(end, line.cell_length)))

    def primary_activation_targets(self, region: Region):
        """Each painted cell offers its own segment's effect, so hints reach every stretch."""
        return self.segment_at(region.x - self.content_region.x).activation_targets(self, region)

    def row_activation_targets(self, region: Region):
        return super().primary_activation_targets(region)

    async def on_click(self, event: events.Click) -> None:
        # Segments are measured from the painted content, not the row's padding.
        await self.segment_at(event.x - self.gutter.left).click(self, event)

    def expand_members(self, expanded: bool) -> None:
        group = self.header_group
        if group.expanded != expanded:
            group.toggle_members()


class GroupTitle(Activates, GroupHeaderLine, can_focus=True):
    """A group's title line that only names its members: activating it toggles them."""

    def activate(self) -> None:
        self.header_group.toggle_members()


class SidebarReaderLayout(VerticalLayout):
    """Native flow, preserving the viewport's reader before placements change."""

    @height_dependency(FLOW_HEIGHT)
    def arrange(self, parent: Widget, children: list[Widget], size: Size, greedy: bool=True):
        placements = super().arrange(parent, children, size, greedy)
        parent.query_ancestor(TargetTree).preserve_reader(placements)
        return placements


class SidebarMembers(VerticalGroup):
    """A group's member rows, indented under its disclosure."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.layout = SidebarReaderLayout()
        self.styles.margin = (0, 0, 0, 2)


class RowReconciliation:
    """One sync's model membership and transferable native rows, never a retained cache."""

    def __init__(self, tree: TargetTree) -> None:
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
        self.sources = {
            key: dict.fromkeys(islice(groups, max(0, demand[key])))
            for key, groups in self.sources.items()
        }
        self.requests = requests

    @staticmethod
    def sync(method):
        @wraps(method)
        def synchronized(view, *args, **kwargs):
            with view.reconciliation_tree.reconcile_members():
                return method(view, *args, **kwargs)

        return synchronized

    def finish(self) -> None:
        for group, keys in self.requests.items():
            if any(self.sources.get(key) for key in keys):
                group.sync_members(frozenset(group.member_keys))

    def retains(self, key: str, group: SidebarGroup) -> bool:
        return key in self.listed and group in self.sources.get(key, ())

    def has_spare(self, key: str):
        return bool(self.sources.get(key))

    def take(self, key: str, destination: SidebarGroup):
        sources = self.sources.get(key)
        if not sources:
            return None
        source, _ = sources.popitem()
        row = source.rows.pop(key)
        row.reparent(destination.member_container)
        source.rows_changed()
        return row


class KeyedRows[KeyT]:
    """Retain native member widgets by model key; the container owns their order."""

    def keep_row(self, key: KeyT) -> bool:
        return False

    def should_mount(self, key: KeyT) -> bool:
        return True

    @abstractmethod
    def create_row(self, key: KeyT):
        ...

    def update_row(self, key: KeyT, row) -> None:
        pass

    def retire_row(self, row: Widget) -> None:
        row.remove()

    def rows_changed(self) -> None:
        pass

    def place_row(self, row, index: int) -> None:
        """Publish list-position facts only for a new or moved row."""

    def reconcile_keys(self, keys: Iterable[KeyT], *, changed: frozenset[KeyT]):
        rows = self.rows
        retained = set(rows.values())
        previous = {
            row: index
            for index, row in enumerate(
                child for child in self.member_container.children if child in retained
            )
        }
        wanted = set(keys)
        retired = [key for key in rows if key not in wanted and not self.keep_row(key)]
        for key in retired:
            self.retire_row(rows.pop(key))
        mounted = []
        for key in keys:
            if key not in rows:
                if not self.should_mount(key):
                    continue
                current = self.create_row(key)
                rows[key] = current
                self.update_row(key, current)
                if not current.is_attached:
                    self.member_container.mount(current)
                mounted.append(current)
            elif key in changed or not rows[key].is_attached:
                self.update_row(key, rows[key])
        ordered = tuple(rows[key] for key in keys if key in rows)
        positions = {row: index for index, row in enumerate(ordered)}
        for row, index in positions.items():
            if previous.get(row) != index:
                self.place_row(row, index)
        live = tuple(
            child for child in self.member_container.children if child in positions
        )
        reordered = bool(ordered) and live != ordered
        if reordered:
            self.member_container.sort_children(
                key=lambda child: positions.get(child, len(positions))
            )
        if retired or mounted or reordered:
            self.rows_changed()
        return ordered


class SidebarGroup[RowT: "ListedRow"](KeyedRows[str], VerticalGroup):
    """A common header/disclosure and optional bounded member viewport."""

    navigation_header = False
    leading_segments: tuple[HeaderSegment, ...] = (Disclosure(2),)
    trailing_segments: tuple[HeaderSegment, ...] = ()

    expanded = reactive(False, init=False)

    _rows_pending = False
    """A reconciliation ran out of its step and left rows unmounted."""

    _step_full = False
    """The step used up its budget, so the row it just reached is its last."""

    _row_mounting: Worker[None] | NoWorker = NoWorker()
    """The pending-row worker, or unscheduled work answering the same queries."""

    def __init__(
        self,
        row: GroupHeaderLine,
        *,
        expanded: bool,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.row = row
        self.rows: dict[str, RowT] = {}
        # The row is the group's whole header line, one row high across the group.
        row.styles.width = "1fr"
        row.styles.height = 1
        row.styles.text_wrap = "nowrap"
        self.member_container = SidebarMembers()
        self.expanded = expanded

    def compose(self) -> ComposeResult:
        yield self.row
        yield self.member_container

    def on_mount(self) -> None:
        if self.accepts_members():
            self.sync_members(frozenset(self.member_keys))

    def toggle_members(self) -> None:
        if self.accepts_members():
            self.expanded = not self.expanded
            self.sync_members(frozenset(self.member_keys))

    def sync_members(self, changed: frozenset[str]) -> None:
        """Reconcile model-owned member rows and repaint the named members."""

    def watch_expanded(self, previous: bool, expanded: bool) -> None:
        self.row.refresh(layout=False)
        if self.is_mounted:
            self.member_container.set_display_constraint(
                "members", self.members_visible
            )
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

    def rows_for_target(self, target: str):
        if not self.accepts_members():
            return ()
        header = (
            (self.row,)
            if self.navigation_header and self.row.target_name == target
            else ()
        )
        member = self.rows.get(target)
        return (
            *header,
            *((member,) if member is not None and member.is_navigation_row() else ()),
        )

    def accepts_navigation(self) -> bool:
        return self.display and self.accepts_members()

    def accepts_members(self):
        """Native membership is valid until this group starts retirement."""
        return self.is_attached and not self.is_leaving

    def keep_row(self, key: str) -> bool:
        return self.reconciliation_tree.row_reconciliation.retains(key, self)

    def should_mount(self, key: str) -> bool:
        if self.reconciliation_tree.row_reconciliation.has_spare(key):
            return True
        if not self.members_visible:
            return False
        if self._step_full:
            self._rows_pending = True
            return False
        # A step always mounts the row it reached, so every step makes progress.
        self._step_full = perf_counter_ns() >= self._row_deadline
        return True

    @abstractmethod
    def new_row(self, key: str):
        ...

    def create_row(self, key: str):
        spare = self.reconciliation_tree.row_reconciliation.take(key, self)
        return spare if spare is not None else self.new_row(key)

    def update_row(self, key: str, row: RowT) -> None:
        self.show_member(key, row)

    def place_row(self, row: RowT, index: int) -> None:
        row.place(index)

    @property
    @abstractmethod
    def member_keys(self):
        """Keys listed by this group's current model, including hidden rows."""

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
    def reconcile_rows(self, *, changed: frozenset[str]):
        """Retain rows by identity; mount, remove and reorder only what differs.

        Neither a title/status change nor a selection repaint remounts the list.
        New rows are created and mounted in key order (the top of the list
        first) for one layout step's time; the rest follow a step's worth per
        frame, so each frame lays out and paints only the rows just added.
        """
        if not self.accepts_members():
            return ()
        keys = self.matching_keys
        tree = self.reconciliation_tree
        self.set_display_constraint("sidebar-search", bool(keys) or not tree.search)
        self.member_container.set_display_constraint("members", self.members_visible)
        self._rows_pending = False
        self._step_full = False
        self._row_deadline = perf_counter_ns() + self.screen.LAYOUT_STEP_NS
        ordered = self.reconcile_keys(keys, changed=changed)
        if self._rows_pending and self._row_mounting.is_finished:
            self._row_mounting = self.run_worker(
                self._mount_pending_rows(), group="sidebar-rows"
            )
        return ordered

    async def _mount_pending_rows(self) -> None:
        """Mount the rows reconciliation left, a step's worth after each frame."""
        while self._rows_pending and self.accepts_members() and self.members_visible:
            self._rows_pending = False
            refreshed = asyncio.Event()
            self.call_after_refresh(refreshed.set)
            await refreshed.wait()
            if not self.accepts_members() or not self.members_visible:
                return
            # No model change: only the rows created now are painted.
            self.sync_members(frozenset())


class SidebarChange(ABC):
    """The changed model rows choose which native rows need work."""

    @abstractmethod
    def apply_comms(self, sidebar: CommsSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        ...

    @abstractmethod
    def apply_welcome(self, channel_list: SidebarGroup, thread_list: SidebarGroup) -> None:
        ...

    @abstractmethod
    def apply_relationships(self, groups: Iterable[RelationshipRows]) -> None:
        ...

    @abstractmethod
    def apply_activity(self, view: ChannelActivity) -> None:
        ...

    def apply_navigation(self, sidebar: CommsSidebar) -> None:
        sidebar.navigation.apply()


class AllSidebarRows(SidebarChange):
    def apply_comms(self, sidebar: CommsSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        sidebar.open_views = sidebar.find_open_views()
        with sidebar.reconcile_members():
            for name, group in sidebar.groups.items():
                group.present(rows[name])
                group.sync_members(frozenset(group.member_keys))

    def apply_welcome(self, channel_list: SidebarGroup, thread_list: SidebarGroup) -> None:
        channel_list.sync_members(frozenset(channel_list.member_keys))
        thread_list.sync_members(frozenset(thread_list.member_keys))

    def apply_relationships(self, groups: Iterable[RelationshipRows]) -> None:
        for group in groups:
            group.sync_members(frozenset(group.member_keys))

    def apply_activity(self, view: ChannelActivity) -> None:
        view.call_next(view.sync_members, frozenset(view.member_keys))


@dataclass(frozen=True)
class ChangedChannels(SidebarChange):
    names: frozenset[str]

    def apply_comms(self, sidebar: CommsSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        with sidebar.reconcile_members():
            for name in self.names:
                group = sidebar.groups.get(name)
                if group is not None:
                    group.sync_members(group.present(rows[name]))

    def apply_welcome(self, channel_list: SidebarGroup, thread_list: SidebarGroup) -> None:
        channel_list.sync_members(self.names)
        # A changed channel can change the welcome thread list's order.
        thread_list.sync_members(frozenset())

    def apply_relationships(self, groups: Iterable[RelationshipRows]) -> None:
        pass

    def apply_activity(self, view: ChannelActivity) -> None:
        references = view.model_state.shown.observation.require_snapshot().references
        if view.view.conversation.destination(references).name in self.names:
            view.call_next(view.sync_members, frozenset(view.member_keys))


@dataclass(frozen=True)
class ChangedThreads(SidebarChange):
    names: frozenset[str]

    def apply_comms(self, sidebar: CommsSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        for group in sidebar.groups.values():
            group.repaint_members(self.names)

    def apply_welcome(self, channel_list: SidebarGroup, thread_list: SidebarGroup) -> None:
        thread_list.sync_members(self.names)

    def apply_relationships(self, groups: Iterable[RelationshipRows]) -> None:
        for group in groups:
            changed = group.keys_for_threads(self.names)
            if changed:
                group.sync_members(changed=changed)

    def apply_activity(self, view: ChannelActivity) -> None:
        changed = view.changed_keys(self.names)
        if changed:
            view.call_next(view.sync_members, changed)

    def apply_navigation(self, sidebar: CommsSidebar) -> None:
        pass


EMPTY = SidebarModel(lambda callback: None)


class SidebarModelState(ABC):
    @abstractmethod
    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        """Whether this state's sidebar displays this direct child."""

    def root(self):
        raise RuntimeError("The sidebar has no observed service.")

    @property
    def shown(self) -> SidebarModel:
        return EMPTY

    def shows_model(self) -> bool:
        return False

    def serves(self, path) -> bool:
        return False

    def observes(self, observed: Observing) -> bool:
        return False

    def unsubscribe(self, view: SidebarModelView) -> None:
        pass

    def changes(self, changes):
        return changes

    def apply(self, view: SidebarModelView, changes) -> None:
        pass

    def present(self, view: SidebarModelView):
        view.app.coordination_access.show_sidebar(view, False)
        return self


class Detached(SidebarModelState):
    """No opened service or model belongs to this view."""

    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        return False


@dataclass(frozen=True)
class FailedSidebarState(SidebarModelState):
    observed: FailedObservation

    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        return child is view.unavailable

    def present(self, view: SidebarModelView):
        view.unavailable.update(f"Comms unavailable\n{self.observed.error}")
        view.app.coordination_access.show_sidebar(view, view.accepts_observation())
        return self


@dataclass(frozen=True)
class BoundSidebar(SidebarModelState):
    observed: Observing

    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        return (child is view.unavailable) == self.observed.sidebar.observation.shows_status()

    def root(self):
        return self.observed.root

    def serves(self, path) -> bool:
        return self.observed.root == path

    def observes(self, observed: Observing) -> bool:
        return self.observed is observed

    def unsubscribe(self, view: SidebarModelView) -> None:
        self.observed.sidebar.channels.unsubscribe(view.channels_changed)
        self.observed.sidebar.threads.unsubscribe(view.threads_changed)

    def present(self, view: SidebarModelView):
        view.unavailable.update(self.observed.sidebar.observation.status_text())
        shown = view.accepts_observation()
        view.app.coordination_access.show_sidebar(view, shown)
        if not shown:
            return Behind(self.observed)
        return self.present_current()

    def present_current(self):
        return self


class Current(BoundSidebar):
    def shows_model(self) -> bool:
        return True

    def apply(self, view: SidebarModelView, changes) -> None:
        if changes:
            view.sync(**changes)

    @property
    def shown(self) -> SidebarModel:
        return self.observed.sidebar


class Behind(BoundSidebar):
    def present_current(self):
        return Current(self.observed)

    def changes(self, changes):
        return dict(change=AllSidebarRows(), reorder=True)


class SidebarModelView(CoreEventReceiver, Widget):
    app: ToadApp
    """A widget showing the observed service's sidebar model.

    Core's model is observed only while a view shows it. Changes that arrive
    while this one is hidden are applied in one pass when it shows again.
    """

    def __init__(self, *args: Widget, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable = Static("", markup=False)

    async def on_mount(self) -> None:
        await self.mount(self.unavailable)
        self.watch_model_state(self.model_state)
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        observed = await self.app.preparation.run_thread(
            self.app.coordination_access.observation.observed
        )
        observed.show_sidebar(self)

    def on_unmount(self) -> None:
        self.stop_showing()

    def on_show(self) -> None:
        self.present()

    def sidebar_visibility_changed(self) -> None:
        self.present()

    model_state: reactive[SidebarModelState] = reactive(Detached, repaint=False, always_update=True)

    def watch_model_state(self, state: SidebarModelState) -> None:
        for child in self.children:
            child.display = state.shows_child(self, child)

    @property
    def navigation_root(self):
        return self.model_state.root()

    @abstractmethod
    def accepts_observation(self) -> bool:
        """Whether this view shows the model now."""

    def model_replaced(self) -> None:
        """Retire what showed the previous service's rows."""

    @abstractmethod
    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        """Apply the model's declared row change."""

    def unsubscribe(self) -> None:
        self.model_state.unsubscribe(self)
        self.model_state = Detached()

    def stop_showing(self) -> None:
        self.app.coordination_access.show_sidebar(self, False)
        self.unsubscribe()

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        self.unsubscribe()
        self.model_state = FailedSidebarState(observed)
        self.model_replaced()
        self.display = True
        self.present()

    def bind_observation(self, observed: Observing) -> None:
        if self.model_state.observes(observed):
            return
        self.unsubscribe()
        self.model_state = Behind(observed)
        observed.sidebar.channels.subscribe(self.channels_changed)
        observed.sidebar.threads.subscribe(self.threads_changed)
        self.model_replaced()
        self.present()

    def channels_changed(self, changes: Changes[str]) -> None:
        self.present(
            change=ChangedChannels(frozenset((*changes.added, *changes.changed))),
            reorder=bool(changes.added or changes.removed or changes.order is not None),
        )

    def threads_changed(self, changes: Changes[str]) -> None:
        self.present(
            change=ChangedThreads(
                frozenset((*changes.added, *changes.removed, *changes.changed))
            )
        )

    def present(self, **changes) -> None:
        """Publish the next state before it applies pending model changes."""
        previous = self.model_state
        self.model_state = previous.present(self)
        self.model_state.apply(self, previous.changes(changes))

    @handles(CoordinationObserved)
    async def coordination_observed(self, event: CoordinationObserved) -> None:
        self.app.coordination_access.observation.observed().show_sidebar(self)

    @handles(ThreadRowStateChanged)
    async def thread_row_state_changed(self, event: ThreadRowStateChanged) -> None:
        """Repaint only the thread rows named by the app event."""
        self.present(change=ChangedThreads(event.names))


class SearchFollower:
    def on_mount(self) -> None:
        self.watch(
            self.query_ancestor(SideBar), "search", self._apply_search, init=True
        )

    def _apply_search(self, value: str) -> None:
        self.search = value.casefold()
        with self.reconcile_members():
            for group in self.navigation_groups:
                group.sync_members(frozenset(group.member_keys))


class TargetTree(HiddenActions, VisibleActions, StepsVerticalCursor, MovesHorizontalCursor, Vertical,
                 scopes={HiddenActions: (CursorCommand,)}):
    """Common row keyboard mechanics; specialized trees own data and state."""

    navigation_groups: Iterable[SidebarGroup]
    search = ""

    def matches(self, key: str) -> bool:
        return self.search in key.casefold()

    def preserve_reader(self, placements: list[WidgetPlacement]) -> None:
        """A sidebar viewport may retain its reader across a native relayout."""

    _member_reconciliation = None
    _member_reconciliation_depth = 0

    @property
    def member_keys(self):
        return (key for group in self.navigation_groups for key in group.member_keys)

    @property
    def row_reconciliation(self):
        if not self._member_reconciliation_depth:
            raise RuntimeError("Row reconciliation requires an active member sync")
        if self._member_reconciliation is None:
            self._member_reconciliation = RowReconciliation(self)
        return self._member_reconciliation

    @contextmanager
    def reconcile_members(self):
        self._member_reconciliation_depth += 1
        try:
            yield
        finally:
            try:
                if (
                    self._member_reconciliation_depth == 1
                    and self._member_reconciliation is not None
                ):
                    self._member_reconciliation.finish()
            finally:
                self._member_reconciliation_depth -= 1
                if not self._member_reconciliation_depth:
                    self._member_reconciliation = None

    @property
    def reconciliation_tree(self):
        return self

    @abstractmethod
    def show_row_menu(self, row: CommsRow, offset: Offset) -> None:
        ...

    def row_selected(self, row: CommsRow) -> bool:
        """A tree that keeps no selected set selects no row."""
        return False

    def remember_row(self, row: CommsRow) -> None:
        """A tree that keeps no selected set has no anchor to remember."""

    def pointer_select(self, row: CommsRow, *, control: bool=False, shift: bool=False, menu: bool=False) -> None:
        """A tree that keeps no selected set ignores pointer selection."""

    def apply_selection(self) -> None:
        """A tree that keeps no selected set has nothing to prune."""

    @property
    @abstractmethod
    def navigation_root(self):
        ...

    def row_current(self, row: CommsRow) -> bool:
        return self.app.workspace_sessions.visible_target(self.navigation_root).matches(
            row.target
        )

    def rows_for_target(self, target: NavigationTarget):
        return tuple(
            row for group in self.navigation_groups for row in target.rows_in(group)
        )

    @property
    def current_rows(self):
        target = self.app.workspace_sessions.visible_target(self.navigation_root)
        return tuple(
            row
            for group in self.navigation_groups
            if group.accepts_navigation()
            for row in target.rows_in(group)
            if row is group.row or group.members_visible
        )

    @handles(SessionSelected)
    def session_selected(self, event: SessionSelected) -> None:
        if not self.rows:
            return
        workspace = self.app.workspace_sessions
        previous = workspace.target_for_mode(
            event.previous_mode, self.navigation_root
        )
        current = workspace.visible_target(self.navigation_root)
        for row in set(self.rows_for_target(previous)).symmetric_difference(
            self.rows_for_target(current)
        ):
            row.paint_current()

    @property
    def rows(self) -> list[CommsRow]:
        return [
            row for group in self.navigation_groups for row in group.navigation_rows
        ]

    def action_cursor_right(self) -> None:
        """Right expands the focused header's members, as in any tree."""
        if (row := self.app.focused) in self.rows:
            row.expand_members(True)

    def action_cursor_left(self) -> None:
        """Left collapses them."""
        if (row := self.app.focused) in self.rows:
            row.expand_members(False)

    def step_vertical(self, direction: int) -> None:
        rows = self.rows
        if rows:
            focused = self.app.focused
            index = (
                rows.index(focused)
                if focused in rows
                else -1 if direction > 0 else len(rows)
            )
            row = rows[max(0, min(len(rows) - 1, index + direction))]
            self.focus_row(row)

    def focus_row(self, row: CommsRow) -> None:
        row.scroll_visible(animate=False, immediate=True)
        self.screen.set_focus(row, scroll_visible=False)

    def open_selected(self) -> None:
        if (row := self.app.focused) in self.rows:
            row.open_selected()


class SelectsTargets(TargetTree):
    """A tree that keeps a selected set of targets: rows select by pointer and keyboard,
    and the set survives navigation while its rows exist."""

    @property
    @abstractmethod
    def selection_state(self):
        ...

    @abstractmethod
    def selection_for(self, row: CommsRow):
        ...

    def accepts_selection(self) -> bool:
        return True

    @abstractmethod
    def row_for(self, selection):
        ...

    def row_selected(self, row: CommsRow) -> bool:
        return self.selection_for(row) in self.selection_state.selected_targets

    @contextmanager
    def selection_change(self):
        previous = set(self.selection_state.selected_targets)
        try:
            yield
        finally:
            changed = previous.symmetric_difference(self.selection_state.selected_targets)
            for row in self.rows:
                if self.selection_for(row) in changed:
                    row.refresh_paint()

    def remember_row(self, row: CommsRow) -> None:
        """Navigation establishes a range anchor; it is not bulk selection."""
        rows = self.rows
        if self.accepts_selection() and row in rows:
            with self.selection_change():
                state = self.selection_state
                state.selected = self.selection_for(row)
                state.selected_targets = ()

    def pointer_select(self, row: CommsRow, *, control: bool=False, shift: bool=False, menu: bool=False) -> None:
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
                start, end = sorted(
                    (identities.index(state.selected), identities.index(selected))
                )
                span = identities[start : end + 1]
                state.selected_targets = (
                    tuple(dict.fromkeys((*current, *span))) if control else span
                )
            elif control:
                state.selected_targets = (
                    tuple(item for item in current if item != selected)
                    if selected in current
                    else (*current, selected)
                )
                state.selected = selected
            else:
                state.selected = selected
                state.selected_targets = (selected,)

    def apply_selection(self) -> None:
        with self.selection_change():
            state = self.selection_state
            shown = {self.selection_for(row) for row in self.rows}
            state.selected_targets = tuple(
                identity for identity in state.selected_targets if identity in shown
            )
