"""Shared disclosure, row navigation and keyed tree presentation mechanics."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable
from contextlib import contextmanager
from functools import (
    partial,
    wraps,
)
from itertools import islice
from time import perf_counter_ns
from typing import ClassVar
from textual.events import (
    Click,
    Mount,
)
from textual.layout import WidgetPlacement
from toad.sidebar_contracts import (
    MemberRows,
    TargetRows,
)

from metaclass_registry.mro_dispatch import handles
from toad.widget_actions import Activates
from textual._measurement import FLOW_HEIGHT, height_dependency
from textual.app import ComposeResult
from textual.navigation import CursorCommand, MovesHorizontalCursor
from toad.widget_actions import HiddenActions, StepsVerticalCursor, VisibleActions
from textual.containers import Vertical, VerticalGroup
from textual import events
from textual._activation import (
    CallbackTarget,
    ContextActivation,
    PrimaryActivation,
)
from rich.style import Style
from textual.content import Content
from textual.strip import Strip
from textual.geometry import Offset, Region, Size
from textual.layouts.vertical import VerticalLayout
from textual.reactive import reactive
from textual.widget import Widget
from textual.worker import Worker
from textual.widgets import Static

from toad.core.events import SessionSelected
from toad.native_style import EllipsisOverflow, NoWrap, PointerCursor, TwoRows
from toad.no_worker import NoWorker
from toad.widgets.side_bar import SideBar
from textual import on
from ui_theme.effects import NEW_MESSAGE

from toad.widgets.selection import HoverSelection, ViewLabel
from toad.core_event_carrier import CoreEventReceiver
from toad.keyed_rows import KeyedRows
from toad.navigation_target import NavigationTarget
from toad.tone_paint import AlternatingTone
from toad.widget_actions import OpenSelectedAction, OpensSelected


class TargetTreeMember(HiddenActions):
    """A navigation control belongs to one required native tree. The tree is bound when the
    member mounts and released when it unmounts, so painting never walks the DOM to find it."""

    _bound_tree: TargetTree | None = None

    @on(events.Mount)
    def _bind_navigation_tree(self) -> None:
        self._bound_tree = self.query_ancestor(TargetTree)

    @on(events.Unmount)
    def _release_navigation_tree(self) -> None:
        self._bound_tree = None

    @property
    def navigation_tree(self) -> TargetTree:
        # Unmounted, the answer is the same as before: the ancestor search, which raises.
        return self._bound_tree or self.query_ancestor(TargetTree)

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


class DetailedRow(TwoRows, NoWrap, EllipsisOverflow, Widget):
    """A sidebar row whose second line is its own quieter detail, indented under the title.

    Two rows wanted this independently: a thread's summary and a channel's agent counts.
    The newline, the indent and the muted ink are declared here once, so a row that grows
    a second line cannot invent its own spelling of one.
    """

    detail_indent: ClassVar[int] = 2

    def detail(self) -> str:
        """The row's second line. A row with nothing to add leaves it blank."""
        return ""

    def with_detail(self, title: Content) -> Content:
        return Content.assemble(title, Content.styled(
            f"\n{' ' * self.detail_indent}{self.detail()}", "$text-muted"))


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
        return self.header_lines(Content.assemble(*(content for _, content in pieces)))

    def header_lines(self, line: Content) -> Content:
        """The segment line alone. A header that declares a detail line adds it."""
        return line

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

    def emphasize(self, line: Strip, style: Style, y: int) -> Strip:
        """Only the title carries the row's emphasis; the arrow and controls keep their ink.

        Segments are the first line only, so a detail line beneath them is emphasised whole,
        the way an ordinary row's is.
        """
        if y:
            return line.apply_style(style)
        start, end = self.segment_span(TITLE)
        return Strip.join((line.crop(0, start), line.crop(start, end).apply_style(style),
                           line.crop(end, line.cell_length)))

    def primary_activation_targets(self, region: Region):
        """Each painted cell offers its own segment's effect, so hints reach every stretch."""
        return self.segment_at(region.x - self.content_region.x).activation_targets(self, region)

    def row_activation_targets(self, region: Region):
        return super().primary_activation_targets(region)

    @on(events.Click)
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


class SidebarGroup[RowT: "ListedRow"](MemberRows[str], TargetRows["CommsRow"], KeyedRows[str], VerticalGroup):
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

    @on(events.Mount)
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


class SearchFollower:
    @on(events.Mount)
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


class CommsRow(
    TargetTreeMember, OpensSelected, PrimaryActivation, ContextActivation, CoreEventReceiver, HoverSelection, ViewLabel,
    scopes={HiddenActions: (OpenSelectedAction,)},
):
    """One interactive row: a channel or a thread."""

    text_fades = (NEW_MESSAGE,)

    @property
    def target_name(self) -> str:
        return self.target.name

    def show_menu(self, sidebar: TargetTree, offset: Offset) -> None:
        sidebar.show_row_menu(self, offset)

    def context_activation(self, offset: Offset) -> None:
        self.show_menu(self.navigation_tree, offset)


    can_focus = True

    def focus_on_click(self) -> bool:
        # Pointer activation navigates; keyboard traversal still owns row focus.
        # Avoid restyling/repainting the departing transcript before Click runs.
        return False

    def __init__(self, target: NavigationTarget, label: str) -> None:
        super().__init__(Content(label))
        self.target = target

    @on(Mount)
    def on_mount(self) -> None:
        self.run_effect(NEW_MESSAGE)

    def is_navigation_row(self) -> bool:
        return self.is_attached and not self.is_leaving

    @property
    def current(self) -> bool:
        return self.is_navigation_row() and self.navigation_tree.row_current(self)

    @property
    def selected(self) -> bool:
        return self.is_navigation_row() and self.navigation_tree.row_selected(self)

    @property
    def paint_highlighted(self) -> bool:
        return self.selected or super().paint_highlighted

    def set_label(self, label: str) -> None:
        self.update(Content(label))

    def expand_members(self, expanded: bool) -> None:
        """A member row lists nobody; a group's header line overrides this."""

    @property
    def primary_activation(self):
        return self.open_selected

    def open_selected(self) -> None:
        self.navigation_tree.remember_row(self)
        self.app.run_worker(
            partial(self.app.workspace_sessions.navigation_owner().open_sidebar_target, self.target),
            group="sidebar-open",
        )

    @on(Click)
    def on_click(self, event) -> None:
        if event.button == 3:
            event.stop()
            self.context_activation(event.screen_offset)
            return
        if event.ctrl or event.shift:
            event.stop()
            self.navigation_tree.pointer_select(self, control=event.ctrl, shift=event.shift)
            return
        self.open_selected()


class ListedRow(CommsRow, AlternatingTone):
    """A row its list orders: it alternates on its family's tone pair."""


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
