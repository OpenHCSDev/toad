"""Shared disclosure, row navigation and keyed tree presentation mechanics."""

import asyncio
from contextlib import AsyncExitStack

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalGroup, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from toad.widgets.sidebar_viewport import SidebarHeader


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
        container = VerticalScroll if scrollable else VerticalGroup
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
        await self.reconcile_groups((self,))

    def accepts_members(self):
        """Native membership is valid until this group starts retirement."""
        return self.is_attached and not self._closing and not self._pruning

    def thread_people(self):
        """Specializations supply the original people for a disclosure change."""
        raise NotImplementedError

    def thread_row_inputs(self):
        """Return decorated inputs, retained rows and original source custody."""
        raise NotImplementedError

    def present(self, source):
        """Apply this publication's original group source under member custody."""
        raise NotImplementedError

    async def _reconcile_members(self, prepared_rows, source) -> None:
        """Specializations reconcile their model-owned members here."""

    def rows_changed(self) -> None:
        """Specializations invalidate navigation after native row changes."""

    @classmethod
    async def reconcile_groups(cls, groups, captured=None, *, sources=None):
        """Prepare a publication once, then mutate its original keyed groups.

        Member locks cover both preparation and native delivery. Identical
        decorated inputs share one detached result within this publication;
        retained rows still own reuse between publications.
        """
        from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork

        async with AsyncExitStack() as custody:
            admitted = []
            for group in dict.fromkeys(groups):
                await custody.enter_async_context(group.member_lock)
                admitted.append(group)
            admitted = [group for group in admitted if group.accepts_members()]
            if not admitted:
                return
            if sources is not None:
                for group in admitted:
                    group.present(sources[group])
            runtime = admitted[0].app.preparation
            if captured is None:
                people = {person.thread.name: person for group in admitted
                          for person in group.thread_people()}
                captured = await ThreadRowsWork.capture(
                    runtime, tuple(ThreadRowInput(person) for person in people.values()))
                admitted = [group for group in admitted if group.accepts_members()]
            inputs, retained, witnesses = {}, {}, {}
            for group in admitted:
                rows, retained[group], witnesses[group] = group.thread_row_inputs()
                inputs.update(((group, key), row) for key, row in rows.items())
            # ThreadRowsWork decorates the whole publication through one
            # captured-person lookup, rather than rebuilding it per group.
            prepared = {group: {} for group in admitted}
            missing, pending = {}, {}
            for (group, key), source in captured.for_rows(inputs).items():
                row = retained[group].get(key)
                current = row.thread_preparation(source) if row is not None else None
                if current is None:
                    pending[source] = None
                    missing[group, key] = source
                else:
                    prepared[group][key] = current
            if pending:
                values = await runtime.submit(ThreadRowsWork(tuple(pending)))
                pending.update(zip(pending, values))
            for (group, key), source in missing.items():
                prepared[group][key] = pending[source]
            for group in admitted:
                await group._reconcile_members(prepared[group], witnesses[group])

    async def reconcile_rows(self, keys, rows, create, update, *, replace=None):
        """Retain rows by identity; specialize their construction and content only.

        The caller serializes updates and owns empty-state rows. Neither a
        title/status change nor a selection repaint remounts the list.
        """
        if not self.accepts_members():
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
            if not self.accepts_members():
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
            if not self.accepts_members():
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
