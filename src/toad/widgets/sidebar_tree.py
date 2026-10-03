"""Shared disclosure, row navigation and keyed tree presentation mechanics."""

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalGroup, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from toad.widgets.sidebar_viewport import SidebarHeader


class SidebarMembers(VerticalGroup):
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True


class ScrollingSidebarMembers(VerticalScroll):
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True


class SidebarDisclosure(Static, can_focus=True):
    BINDINGS = [Binding("enter,space", "toggle", "Expand group", show=False)]
    DEFAULT_CSS = "SidebarDisclosure { width: 2; height: 1; pointer: pointer; }"

    def action_toggle(self) -> None:
        self.query_ancestor(SidebarGroup).toggle_members()

    def on_click(self, event) -> None:
        if event.button == 1:
            event.stop()
            self.action_toggle()


class SidebarGroup(VerticalGroup):
    """A common header/disclosure and optional bounded member viewport."""

    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True

    DEFAULT_CSS = """
    SidebarGroup { height: auto; }
    SidebarGroup > .group-header { height: 1; }
    SidebarGroup > .group-header > .group-title { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    SidebarGroup > .group-members { height: auto; margin-left: 2; }
    SidebarGroup > VerticalScroll.group-members { max-height: 12; overflow-x: hidden; }
    """

    class Toggled(Message):
        def __init__(self, group):
            self.group = group
            super().__init__()

    def __init__(self, row, *, expanded: bool, controls=(), scrollable=False,
                 disclosure_type=SidebarDisclosure, **kwargs):
        super().__init__(**kwargs)
        self.member_lock = asyncio.Lock()
        self.row = row
        self.row.add_class("group-title")
        self.expanded = expanded
        self.disclosure = disclosure_type("▾" if expanded else "▸")
        self.controls = controls
        container = ScrollingSidebarMembers if scrollable else SidebarMembers
        self.member_container = container(classes="group-members channel-members")

    def compose(self) -> ComposeResult:
        with SidebarHeader(classes="group-header"):
            yield self.disclosure
            yield self.row
            yield from self.controls
        yield self.member_container

    def toggle_members(self) -> None:
        self.expanded = not self.expanded
        self.disclosure.update("▾" if self.expanded else "▸", layout=False)
        self.post_message(self.Toggled(self))
        self.call_later(self._sync_and_select)

    async def _sync_and_select(self) -> None:
        await self._sync_members()

    async def _sync_members(self) -> None:
        from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork

        async with self.member_lock:
            if not self.is_attached or self._closing or self._pruning:
                return
            inputs = await ThreadRowsWork.capture(
                self.app.preparation,
                tuple(ThreadRowInput(person) for person in self.thread_people()),
            )
            await self._reconcile_members(inputs)

    def thread_people(self):
        """Specializations supply the original people for a disclosure change."""
        raise NotImplementedError

    async def _reconcile_members(self, captured) -> None:
        """Specializations reconcile their model-owned members here."""

    def rows_changed(self) -> None:
        """Specializations invalidate navigation after native row changes."""

    async def prepare_thread_rows(self, inputs, rows, captured):
        """Prepare changed row inputs; retained native rows own their frames."""
        from toad.sidebar_preparation import ThreadRowsWork

        prepared, pending = {}, {}
        for key, source in captured.for_rows(inputs).items():
            row = rows.get(key)
            current = row.thread_preparation(source) if row is not None else None
            if current is None:
                pending[key] = source
            else:
                prepared[key] = current
        if pending:
            values = await self.app.preparation.submit(ThreadRowsWork(tuple(pending.values())))
            prepared.update(zip(pending, values))
        return prepared

    async def reconcile_rows(self, keys, rows, create, update, *, replace=None):
        """Retain rows by identity; specialize their construction and content only.

        The caller serializes updates and owns empty-state rows. Neither a
        title/status change nor a selection repaint remounts the list.
        """
        if not self.is_attached or self._closing or self._pruning:
            return ()
        keys = tuple(keys)
        wanted = set(keys)
        retired = [key for key, row in rows.items()
                   if key not in wanted or (replace is not None and replace(key, row))]
        if retired:
            # A newly opened/closed tab can change several row kinds at once.
            # Retire that exact set in one DOM operation, not an intermediate
            # remove/layout/message-pump turn for every member of the roster.
            await self.member_container.remove_children([rows.pop(key) for key in retired])
            if not self.is_attached or self._closing or self._pruning:
                return ()
        mounted = []
        for key in keys:
            current = rows.get(key)
            if current is None:
                current = rows[key] = create(key)
                mounted.append(current)
            update(key, current)
        if mounted:
            await self.member_container.mount(*mounted)
            if not self.is_attached or self._closing or self._pruning:
                return ()
        ordered = tuple(rows[key] for key in keys)
        reordered = bool(ordered) and tuple(self.member_container.children) != ordered
        if reordered:
            positions = {row: index for index, row in enumerate(ordered)}
            self.member_container.sort_children(key=positions.__getitem__)
        if retired or mounted or reordered:
            self.rows_changed()
        return ordered


class TargetTree(Vertical):
    """Common row keyboard mechanics; specialized trees own data and state."""

    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True

    DEFAULT_CSS = """
    TargetTree .-selected, TargetTree .-selected:hover, TargetTree .-selected:focus {
        background: #ad8bf5; color: #161021 !important; text-style: bold;
    }
    TargetTree:ansi .-selected, TargetTree:ansi .-selected:hover, TargetTree:ansi .-selected:focus {
        background: ansi_magenta; color: ansi_black !important; text-style: bold;
    }
    """

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
