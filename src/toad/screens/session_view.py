"""Logical session surfaces hosted by the one native WorkspaceScreen."""
from textual.containers import Vertical
from textual.widget import Widget
from textual.reactive import reactive
from toad.widgets.side_bar import SidebarFocusOwner


class SessionView(SidebarFocusOwner, Vertical):
    title = reactive("")
    sub_title = reactive("")

    DEFAULT_CSS = "SessionView { width: 1fr; height: 1fr; }"
    AUTO_FOCUS = ""
    COMMANDS = set()
    footer_compact = False
    shows_channels = True
    _first_frame_presented = False

    @property
    def is_current(self) -> bool:
        return self.app.workspace_sessions.selected is self and self.screen.is_current

    @property
    def coordination_root(self) -> str | None:
        return None

    def sidebar_focus_target(self) -> Widget | None:
        return None

    def channels_context(self) -> tuple[str, str]:
        return "", ""

    def relationship_context(self) -> tuple[str, str | None]:
        return self.channels_context()[0], self.coordination_root

    def activate_session(self) -> None:
        """Bind surface-local observers before its selected frame."""

    def capture_navigation(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar
        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.capture_navigation()

    async def prepare_navigation(self) -> bool:
        """Reconcile only this logical source's sidebar navigation and observers."""
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        changed = False
        for sidebar in self.query(SideBar):
            panels = tuple(sidebar.query(SideBarCollapsible))
            before = tuple(panel.collapsed for panel in panels)
            changed |= sidebar.restore_navigation()
            changed |= before != tuple(panel.collapsed for panel in panels)
            sidebar.schedule_hydration()
        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.prepare_navigation()
            self.call_after_first_frame(sidebar, sidebar.start_navigation_hydration)
        return changed

    def restore_navigation_scroll(self) -> bool:
        from toad.widgets.comms_sidebar import CommsSidebar
        sidebar = self.query_one_optional(CommsSidebar)
        return sidebar.restore_scroll() if sidebar is not None else False

    async def prepare_presentation(self) -> None:
        """Restore source-bound rich presentation for the selected logical view."""

    async def retire_presentation(self) -> None:
        """Release rich presentation without stopping its operational sources."""

    async def close_presentation(self) -> None:
        """Views without retained operational sources need no domain finalization."""

    async def on_unmount(self) -> None:
        await self.close_presentation()

    def call_after_first_frame(self, owner, callback) -> None:
        self.screen.call_after_first_frame(owner, callback)

    async def wait_presented(self) -> bool:
        return await self.screen.wait_presented() and self.is_current

    @property
    def viewport_presentation(self):
        return self.screen.viewport_presentation
