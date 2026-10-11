"""Shared disclosure, row navigation and keyed tree presentation mechanics."""

import asyncio
from time import perf_counter_ns

from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.containers import Vertical, VerticalGroup, VerticalScroll
from textual.widgets import Static

from toad.widgets.sidebar_viewport import SidebarHeader


class SidebarDisclosure(Static, can_focus=True):
    BINDINGS = [Binding("enter,space", "toggle", "Expand group", show=False)]
    DEFAULT_CSS = "SidebarDisclosure { width: 2; height: 1; pointer: pointer; }"

    def render(self):
        return "▾" if self.query_ancestor(SidebarGroup).expanded else "▸"

    def action_toggle(self) -> None:
        self.query_ancestor(SidebarGroup).toggle_members()

    def on_click(self, event) -> None:
        if event.button == 1:
            event.stop()
            self.action_toggle()


class SidebarGroup(VerticalGroup):
    """A common header/disclosure and optional bounded member viewport."""

    DEFAULT_CSS = """
    SidebarGroup { height: auto; }
    SidebarGroup > .group-header { height: 1; }
    SidebarGroup > .group-header > .group-title { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    SidebarGroup > .group-members { display: none; height: auto; margin-left: 2; }
    SidebarGroup.-expanded > .group-members { display: block; }
    SidebarGroup > VerticalScroll.group-members { max-height: 12; overflow-x: hidden; }
    """

    expanded = reactive(False, init=False, toggle_class="-expanded")

    _rows_pending = False
    """A reconciliation ran out of its step and left rows unmounted."""

    _row_mounting = None
    """The worker mounting pending rows after the following frames."""

    def __init__(self, row, *, expanded: bool, controls=(), scrollable=False,
                 disclosure_type=SidebarDisclosure, **kwargs):
        super().__init__(**kwargs)
        self.row = row
        self.row.add_class("group-title")
        self.disclosure = disclosure_type()
        self.controls = controls
        container = VerticalScroll if scrollable else VerticalGroup
        self.member_container = container(classes="group-members channel-members")
        self.expanded = expanded

    def compose(self) -> ComposeResult:
        with SidebarHeader(classes="group-header"):
            yield self.disclosure
            yield self.row
            yield from self.controls
        yield self.member_container

    def toggle_members(self) -> None:
        self.expanded = not self.expanded
        self.sync_members()

    def sync_members(self, changed: frozenset[str] | None = None) -> None:
        """Specializations reconcile their model-owned member rows; repaint ``changed`` (all if None)."""

    def watch_expanded(self, previous: bool, expanded: bool) -> None:
        self.disclosure.refresh(layout=False)
        if self.is_mounted:
            self.members_visibility_changed(previous, expanded)
            self.rows_changed()

    def members_visibility_changed(self, previous: bool, expanded: bool) -> None:
        """Specializations preserve existing reader intent across disclosure."""

    @property
    def visible_members(self):
        return tuple(self.member_container.children) if self.expanded and self.display else ()

    def admits_row(self, row) -> bool:
        return self.display and (row is self.row or self.expanded)

    def accepts_members(self):
        """Native membership is valid until this group starts retirement."""
        return self.is_attached and not self._closing and not self._pruning

    def rows_changed(self) -> None:
        """Specializations invalidate navigation after native row changes."""

    def reconcile_rows(self, keys, rows, create, update, *, replace=None):
        """Retain rows by identity; mount, remove and reorder only what differs.

        Neither a title/status change nor a selection repaint remounts the list.
        New rows are created and mounted in key order (the top of the list
        first) for one layout step's time; the rest follow a step's worth per
        frame, so each frame lays out and paints only the rows just added.
        """
        if not self.accepts_members():
            return ()
        keys = tuple(keys)
        wanted = set(keys)
        retired = [key for key, row in rows.items()
                   if key not in wanted or (replace is not None and replace(key, row))]
        if retired:
            # Retire the exact set in one DOM operation.
            self.member_container.remove_children([rows.pop(key) for key in retired])
        mounted = []
        deadline = perf_counter_ns() + self.screen.LAYOUT_STEP_NS
        for key in keys:
            current = rows.get(key)
            if current is None:
                if perf_counter_ns() >= deadline:
                    self._rows_pending = True
                    continue
                current = rows[key] = create(key)
                update(key, current)
                # Mounted one at a time: styling each is most of its cost,
                # and the deadline must see it.
                self.member_container.mount(current)
                mounted.append(current)
                continue
            update(key, current)
        if self._rows_pending and (self._row_mounting is None or self._row_mounting.is_finished):
            self._row_mounting = self.run_worker(self._mount_pending_rows(), group="sidebar-rows")
        ordered = tuple(rows[key] for key in keys if key in rows)
        live = tuple(child for child in self.member_container.children if not child._pruning)
        reordered = bool(ordered) and live != ordered
        if reordered:
            positions = {row: index for index, row in enumerate(ordered)}
            self.member_container.sort_children(key=lambda child: positions.get(child, len(positions)))
        if retired or mounted or reordered:
            self.rows_changed()
        return ordered

    async def _mount_pending_rows(self) -> None:
        """Mount the rows reconciliation left, a step's worth after each frame."""
        while self._rows_pending and self.accepts_members():
            self._rows_pending = False
            refreshed = asyncio.Event()
            self.call_after_refresh(refreshed.set)
            await refreshed.wait()
            # No model change: only the rows created now are painted.
            self.sync_members(frozenset())


class TargetTree(Vertical):
    """Common row keyboard mechanics; specialized trees own data and state."""

    @property
    def selection_state(self):
        raise NotImplementedError

    def selection_for(self, row):
        raise NotImplementedError

    def accepts_selection(self) -> bool:
        return True

    def remember_row(self, row) -> None:
        """Navigation establishes a range anchor; it is not bulk selection."""
        rows = self._ordered_rows()
        if self.accepts_selection() and row in rows:
            self._cursor = rows.index(row)
            state = self.selection_state
            state.selected = self.selection_for(row)
            state.selected_targets = ()
            self.apply_selection()

    def pointer_select(self, row, *, control=False, shift=False, menu=False) -> None:
        if not self.accepts_selection():
            return
        rows = self._ordered_rows()
        if row not in rows:
            return
        selected = self.selection_for(row)
        state = self.selection_state
        current = state.selected_targets
        if menu and selected in current:
            return
        identities = tuple(self.selection_for(item) for item in rows)
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
        self.apply_selection()

    def apply_selection(self) -> None:
        rows = self._ordered_rows()
        state = self.selection_state
        identities = {self.selection_for(row) for row in rows}
        state.selected_targets = tuple(target for target in state.selected_targets if target in identities)
        for row in rows:
            row.set_class(self.selection_for(row) in state.selected_targets, "-selected")

    @property
    def navigation_root(self):
        raise NotImplementedError

    def sync_current(self) -> None:
        """Every representation of the displayed destination shares its paint."""
        view = self.app.selected_session
        root = self.navigation_root
        target = (view.navigation_target_name
                  if view is not None and root is not None and view.belongs_to_wire(root)
                  else None)
        for row in self._ordered_rows():
            row.current = row.target_name == target

    def _ordered_rows(self):
        raise NotImplementedError

    def focus_row(self, row) -> None:
        rows = self._ordered_rows()
        if row in rows:
            self._cursor = rows.index(row)

    def action_cursor_up(self) -> None:
        rows = self._ordered_rows()
        if rows:
            self._cursor = max(0, min(len(rows) - 1, self._cursor - 1))
            self._apply_cursor(rows)
            rows[self._cursor].focus()

    def action_cursor_down(self) -> None:
        rows = self._ordered_rows()
        if rows:
            self._cursor = min(len(rows) - 1, self._cursor + 1)
            self._apply_cursor(rows)
            rows[self._cursor].focus()

    def _apply_cursor(self, rows) -> None:
        rows[self._cursor].scroll_visible(animate=False)

    def action_open_selected(self) -> None:
        rows = self._ordered_rows()
        focused = self.app.focused
        row = focused if focused in rows else rows[self._cursor] if rows else None
        if row is not None:
            row.action_open_selected()
