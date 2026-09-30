"""Hydration and painted selection of the existing shared channel hierarchy."""
from __future__ import annotations
import asyncio
from textual.widget import Widget
from toad.session_tracker import SidebarSelection, SidebarState
from toad.constants import ALL_COMMS_TARGET
from toad.widgets.comms_sidebar import CommsRow, ChannelGroup

class SidebarNavigation:
    def __init__(self, sidebar):
        self.sidebar = sidebar
        self.ready = asyncio.Event()
        self.revision = 0
        self.worker = None
        self.painted_selection = None
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
    def scroll_containers(self):
        from toad.widgets.side_bar import SideBar, SideBarCollapsible
        panel = self.sidebar.query_ancestor(SideBarCollapsible)
        panels = panel.query_ancestor(SideBar).query_one("#sidebar-panels")
        return panels, panels

    def reset(self) -> None:
        self.ready.clear()
        self.selected_row = None
        self.selection_applied = False
        self.painted_mode = None

    def capture(self) -> None:
        if not self.restoring:
            channel, panels = self.scroll_containers
            self.state.channel_scroll_y = channel.scroll_y
            self.state.panel_scroll_y = panels.scroll_y

    def prepare(self) -> None:
        self.revision += 1
        self.ready.clear()
        # Retained rows belong to their validated route. Hide a changed route
        # before its first frame; ordinary same-route tab switches keep the
        # already-rendered roster while the canonical refresh runs afterward.
        if self.sidebar.observation.enabled and self.sidebar.projection.has_snapshot():
            try:
                if self.sidebar.observation.route_changed():
                    self.sidebar.display = False
            except (OSError, ValueError):
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
            # A refresh callback may precede the resize messages from newly
            # mounted rows. Commit their geometry before scroll_to can clamp
            # the saved offset against the retired, empty shell's extent.
            with self.sidebar.app.batch_update():
                for node in self.sidebar.walk_children(Widget, with_self=True):
                    node._check_refresh()
                for ancestor in self.sidebar.ancestors:
                    if isinstance(ancestor, Widget):
                        ancestor._check_refresh()
                # Host activation already committed a complete native layout.
                # Reflow only if source reconciliation mounted/changed geometry
                # afterward; source readiness is not another host reflow request.
                if self.sidebar.screen._layout_required or self.sidebar.screen._layout_widgets:
                    self.sidebar.screen._refresh_layout(self.sidebar.app.size)
                if self.restore_scroll():
                    self.sidebar.screen._refresh_layout(self.sidebar.app.size, scroll=True)
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
            self.apply()

    def selection_current(self) -> bool:
        """One selected destination has one retained painted row identity."""
        painted = self.selected_row
        return (self.selection_applied and self.painted_selection == self.state.selected
                and (painted is None or painted.is_attached))

    def apply(self, *, force: bool = False) -> None:
        if not force and self.selection_current():
            return
        self.selected_row = None
        for index, row in enumerate(self.sidebar.projection.rows):
            selected = self.selection_for(row) == self.state.selected
            row.set_class(selected, "-selected")
            if selected:
                self.selected_row = row
                self.sidebar._cursor = index
        self.painted_selection = self.state.selected
        self.selection_applied = True

    def restore_scroll(self) -> bool:
        if not self.sidebar.projection.has_snapshot():
            return False
        if self.restoring and self.sidebar.is_attached and self.sidebar.screen is self.sidebar.app.screen:
            return self.state.restore_scroll(*self.scroll_containers)
        return False

    def mode_changed(self, mode_name: str, *, force: bool = False) -> None:
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
        if not force and self.painted_mode == (mode_name, target):
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

