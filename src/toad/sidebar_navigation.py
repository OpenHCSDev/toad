"""Hydration and painted selection of the existing shared channel hierarchy."""
from __future__ import annotations
import asyncio
from toad.session_tracker import SidebarSelection, SidebarState
from toad.constants import ALL_COMMS_TARGET
from toad.widgets.sidebar_viewport import SidebarViewport
from toad.widgets.comms_sidebar import CommsRow, ChannelGroup

class SidebarNavigation:
    def __init__(self, sidebar):
        self.sidebar = sidebar
        self.ready = asyncio.Event()
        self.revision = 0
        self.worker = None
        self.painted_selection = None
        self.painted_targets = ()
        self.selected_row = None
        self.painted_mode = None
        self.selection_applied = False

    @property
    def state(self) -> SidebarState:
        return self.sidebar.app.sidebar_state

    @property
    def restoring(self) -> bool:
        return not self.ready.is_set()

    @property
    def scroll_container(self) -> SidebarViewport:
        from toad.widgets.side_bar import SideBar, SideBarCollapsible
        panel = self.sidebar.query_ancestor(SideBarCollapsible)
        panels = panel.query_ancestor(SideBar).query_one("#sidebar-panels", SidebarViewport)
        return panels

    def reset(self) -> None:
        self.ready.clear()
        self.selected_row = None
        self.selection_applied = False
        self.painted_mode = None

    def capture(self) -> None:
        if not self.restoring:
            self.state.panel_scroll_y = self.scroll_container.scroll_y

    async def prepare(self) -> None:
        self.revision += 1
        revision = self.revision
        self.ready.clear()
        # Retained rows belong to their validated route. Hide a changed route
        # before its first frame; ordinary same-route tab switches keep the
        # already-rendered roster while the canonical refresh runs afterward.
        if self.sidebar.observation.enabled and self.sidebar.projection.has_snapshot():
            snapshot = self.sidebar.projection.snapshot
            try:
                if (await self.sidebar.observation.route_changed()
                        and self.revision == revision
                        and self.sidebar.projection.snapshot is snapshot):
                    self.sidebar.display = False
            except (OSError, ValueError):
                if self.revision == revision and self.sidebar.projection.snapshot is snapshot:
                    self.sidebar.display = False

    def start(self) -> None:
        """Rebuild native rows only after the selected shell has been painted."""
        if not self.sidebar.accepts_publication():
            return
        if self.worker is None or self.worker.is_finished:
            self.worker = self.sidebar.run_worker(
                self.hydrate, group="sidebar-navigation",
            )

    async def hydrate(self) -> None:
        while self.sidebar.accepts_publication():
            revision = self.revision
            await self.sidebar.observation.present_cached()
            if revision == self.revision:
                self.sidebar.call_after_refresh(self.finish, revision)
                return

    def finish(self, revision: int) -> None:
        if revision != self.revision or not self.sidebar.accepts_publication():
            return
        if (self.sidebar.display and self.sidebar.projection.has_snapshot()
                and not self.ready.is_set()):
            # The native sender barrier owns committed row geometry. Restore
            # this reader through its original scroll owner; a changed position
            # needs that owner's next publication before navigation is ready.
            if self.restore_scroll():
                self.sidebar.call_after_refresh(self.finish, revision)
                return
            self.ready.set()

    def selection_for(self, row: CommsRow) -> SidebarSelection:
        channel = row.query_ancestor(ChannelGroup).row.target_name
        return SidebarSelection(channel, row.target_name)

    def remember(self, row: CommsRow) -> None:
        if self.restoring:
            return
        rows = self.sidebar.projection.rows
        if row in rows:
            self.sidebar._cursor = rows.index(row)
            self.state.selected = self.selection_for(row)
            self.state.selected_targets = (self.state.selected,)
            self.apply()

    def pointer_select(self, row: CommsRow, *, control=False, shift=False, menu=False) -> None:
        """Selection is view intent; backend declarations own the operations."""
        if self.restoring:
            return
        rows = self.sidebar.projection.rows
        if row not in rows:
            return
        selected = self.selection_for(row)
        current = self.state.selected_targets
        if menu and selected in current:
            return
        identities = tuple(self.selection_for(item) for item in rows)
        if shift and self.state.selected in identities and selected in identities:
            start, end = sorted((identities.index(self.state.selected), identities.index(selected)))
            span = identities[start:end + 1]
            self.state.selected_targets = tuple(dict.fromkeys((*current, *span))) if control else span
        elif control:
            self.state.selected_targets = (tuple(item for item in current if item != selected)
                                           if selected in current else (*current, selected))
            self.state.selected = selected
        else:
            self.state.selected = selected
            self.state.selected_targets = (selected,)
        self.selection_applied = False
        self.apply()

    def menu_context(self, row: CommsRow):
        from dataclasses import replace
        context = row.target.menu_context(
            self.sidebar, mode_name=row.mode_name,
            channel=self.selection_for(row).channel)
        selected = self.state.selected_targets
        names = tuple(dict.fromkeys(item.target for item in selected))
        if len(names) < 2:
            return context
        return replace(context, targets=names, mode=None,
                       channel={item.target: item.channel for item in selected})

    def selection_current(self) -> bool:
        """One selected destination has one retained painted row identity."""
        painted = self.selected_row
        return (self.selection_applied and self.painted_selection == self.state.selected
                and self.painted_targets == self.state.selected_targets
                and (painted is None or painted.is_attached))

    def rows_changed(self) -> None:
        """Native row replacement invalidates retained navigation paint."""
        self.selection_applied = False
        self.painted_mode = None

    def apply(self) -> None:
        if self.selection_current():
            return
        rows = self.sidebar.projection.rows
        identities = {self.selection_for(row) for row in rows}
        # Collapsed resources still exist, but are not admitted selection or
        # range endpoints. Keep the header as the surviving navigation anchor.
        self.state.selected_targets = tuple(
            target for target in self.state.selected_targets if target in identities)
        if self.state.selected is not None and self.state.selected not in identities:
            header = SidebarSelection(self.state.selected.channel, self.state.selected.channel)
            self.state.selected = header if header in identities else None
            if not self.state.selected_targets and self.state.selected is not None:
                self.state.selected_targets = (self.state.selected,)
        self.selected_row = None
        for index, row in enumerate(rows):
            identity = self.selection_for(row)
            row.set_class(identity in self.state.selected_targets, "-selected")
            if identity == self.state.selected:
                self.selected_row = row
                self.sidebar._cursor = index
        self.painted_selection = self.state.selected
        self.painted_targets = self.state.selected_targets
        self.selection_applied = True

    def restore_scroll(self) -> bool:
        if not self.sidebar.projection.has_snapshot():
            return False
        if self.restoring and self.sidebar.is_attached and self.sidebar.screen is self.sidebar.app.screen:
            viewport = self.scroll_container
            before = viewport.scroll_y
            viewport.scroll_to(y=self.state.panel_scroll_y, animate=False, immediate=True)
            return before != viewport.scroll_y
        return False

    def mode_changed(self, mode_name: str) -> None:
        from toad.screens.comms import CommsScreen

        if not self.sidebar.accepts_publication():
            return
        if self.sidebar.screen is not self.sidebar.app.screen:
            # A tab switch changes presentation, not the channel roster's
            # lifetime. Keep keyed rows and reconcile real source changes on
            # activation; closing the screen still performs normal teardown.
            self.sidebar.projection.pause_spinner()
            return
        target = self.sidebar.screen.target if isinstance(self.sidebar.screen, CommsScreen) and self.sidebar.screen.is_active else None
        if self.painted_mode == (mode_name, target):
            return
        for row in self.sidebar.projection.thread_rows:
            row.current = row.mode_name == mode_name
        for row in self.sidebar.projection.channels.values():
            row.current = row.target_name == target
        self.painted_mode = (mode_name, target)

    async def focus_current(self) -> None:
        """Focus the current session in this authoritative sessions view."""
        await self.sidebar.observation.sync()
        rows = self.sidebar.projection.rows
        if not rows:
            return
        current_mode = self.sidebar.app.selected_mode
        if not any(row.mode_name == current_mode for row in self.sidebar.projection.session_rows):
            aggregate = self.sidebar.projection.channels.get(ALL_COMMS_TARGET)
            if aggregate is not None:
                group = aggregate.query_ancestor(ChannelGroup)
                await group.reveal_members()
                rows = self.sidebar.projection.rows
        target = next((row for row in self.sidebar.projection.session_rows if row.mode_name == current_mode), rows[0])
        self.sidebar._cursor = rows.index(target)
        self.sidebar._apply_cursor(rows)
        target.focus()
