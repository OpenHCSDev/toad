"""Logical session surfaces hosted by the one native WorkspaceScreen."""
from textual.containers import Vertical
from textual.widget import Widget
from textual.reactive import reactive
from toad.widgets.side_bar import SidebarFocusOwner
from pathlib import Path
from toad.project_path_owner import ProjectPathOwner


class SessionView(ProjectPathOwner, SidebarFocusOwner, Vertical):
    title = reactive("")
    sub_title = reactive("")

    DEFAULT_CSS = "SessionView { width: 1fr; height: 1fr; }"
    AUTO_FOCUS = ""
    COMMANDS = set()
    footer_compact = False
    shows_channels = True

    @property
    def project_root(self) -> Path:
        return Path(self.project_path)

    @property
    def is_current(self) -> bool:
        return self.app.workspace_sessions.owns(self) and self.screen.is_current

    @property
    def coordination_root(self) -> str | None:
        return None

    def belongs_to_wire(self, root) -> bool:
        """Unbound views may project the selected wire; bound views stay on it."""
        from pathlib import Path
        source = self.coordination_root
        return source is None or Path(source).expanduser().resolve() == root

    def sidebar_focus_target(self) -> Widget | None:
        return None

    def channels_context(self) -> tuple[str, str]:
        return "", ""

    def relationship_context(self) -> tuple[str, str | None]:
        return self.channels_context()[0], self.coordination_root

    def activate_session(self) -> None:
        """Bind surface-local observers before its selected frame."""

    async def prepare_navigation(self) -> bool:
        """Reconcile only this logical source's sidebar navigation and observers."""
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        changed = False
        for sidebar in self.query(SideBar):
            panels = tuple(sidebar.query(SideBarCollapsible))
            before = tuple(panel.collapsed for panel in panels)
            changed |= sidebar.restore_navigation()
            changed |= before != tuple(panel.collapsed for panel in panels)
            sidebar.schedule_hydration()
        return changed

    async def prepare_presentation(self) -> None:
        """Restore source-bound rich presentation for the selected logical view."""

    async def retire_presentation(self) -> None:
        """Release rich presentation without stopping its operational sources."""

    async def close_presentation(self) -> None:
        """Views without retained operational sources need no domain finalization."""

    def retained_native_presentations(self):
        """Declare admitted native trees; non-native views own no such trees."""
        return ()

    async def wait_presented(self) -> bool:
        return await self.screen.frame_presentation.wait() and self.is_current

    @property
    def viewport_presentation(self):
        return self.screen.viewport_presentation
