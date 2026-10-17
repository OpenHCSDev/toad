"""Hydration and navigation of the existing shared channel hierarchy."""
from __future__ import annotations
import asyncio
from toad.session_tracker import SidebarSelection, SidebarState
from toad.constants import ALL_COMMS_TARGET
from toad.widgets.comms_sidebar import CommsRow

class SidebarNavigation:
    def __init__(self, sidebar):
        self.sidebar = sidebar
        self.ready = asyncio.Event()
        self.revision = 0

    @property
    def state(self) -> SidebarState:
        return self.sidebar.app.sidebar_state

    @property
    def restoring(self) -> bool:
        return not self.ready.is_set()

    def reset(self) -> None:
        self.ready.clear()

    def capture(self) -> None:
        if not self.restoring:
            self.state.panel_scroll_y = self.sidebar.scroll_container.scroll_y

    async def prepare(self) -> None:
        self.revision += 1
        revision = self.revision
        self.ready.clear()
        # Retained rows belong to their validated route. Hide a changed route
        # before its first frame; ordinary same-route tab switches keep the
        # already-rendered roster while the canonical refresh runs afterward.
        if self.sidebar.enabled and self.sidebar.shows_model:
            model = self.sidebar.model
            try:
                if (await self.sidebar.app.coordination_access.route_changed()
                        and self.revision == revision and self.sidebar.model is model):
                    self.sidebar.display = False
            except (OSError, ValueError):
                if self.revision == revision and self.sidebar.model is model:
                    self.sidebar.display = False

    def start(self) -> None:
        """Rebuild native rows only after the selected shell has been painted."""
        if not self.sidebar.accepts_publication():
            return
        self.sidebar.present()
        self.sidebar.call_after_refresh(self.finish, self.revision)

    def finish(self, revision: int) -> None:
        if revision != self.revision or not self.sidebar.accepts_publication():
            return
        if (self.sidebar.display and self.sidebar.shows_model
                and not self.ready.is_set()):
            # The native sender barrier owns committed row geometry. Restore
            # this reader through its original scroll owner; a changed position
            # needs that owner's next publication before navigation is ready.
            if self.restore_scroll():
                self.sidebar.call_after_refresh(self.finish, revision)
                return
            self.ready.set()

    def menu_context(self, row: CommsRow):
        from dataclasses import replace
        context = row.target.menu_context(
            self.sidebar, mode_name=self.sidebar.open_views.get(row.target_name),
            channel=self.sidebar.selection_for(row).channel)
        selected = self.state.selected_targets
        names = tuple(dict.fromkeys(item.target for item in selected))
        if len(selected) < 2:
            return context
        channels = {name: tuple(dict.fromkeys(item.channel for item in selected
                                             if item.target == name))
                    for name in names}
        return replace(context, targets=names, mode=None, channel=channels)

    def apply(self) -> None:
        """Reconcile the canonical selection with visible rows after membership changes."""
        state = self.state
        had_selection = bool(state.selected_targets)
        self.sidebar.apply_selection()
        selected = state.selected
        if selected is not None and self.sidebar.row_for(selected) is None:
            with self.sidebar.selection_change():
                header = SidebarSelection(selected.channel, selected.channel)
                state.selected = header if self.sidebar.row_for(header) is not None else None
                if had_selection and not state.selected_targets and state.selected is not None:
                    state.selected_targets = (state.selected,)

    def restore_scroll(self) -> bool:
        if not self.sidebar.shows_model:
            return False
        if self.restoring and self.sidebar.is_attached and self.sidebar.screen is self.sidebar.app.screen:
            viewport = self.sidebar.scroll_container
            before = viewport.scroll_y
            viewport.scroll_to(y=self.state.panel_scroll_y, animate=False, immediate=True)
            return before != viewport.scroll_y
        return False

    async def focus_current(self) -> None:
        """Focus the current session in this authoritative sessions view."""
        self.sidebar.present()
        rows = self.sidebar.rows
        if not rows:
            return
        self.sidebar.sync_current()
        current = self.sidebar.current_rows
        if not current:
            group = self.sidebar.groups.get(ALL_COMMS_TARGET)
            if group is not None:
                group.reveal_members()
                rows = self.sidebar.rows
                current = self.sidebar.current_rows
        target = current[0] if current else rows[0]
        target.scroll_visible(animate=False)
        target.focus()
