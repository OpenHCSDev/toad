"""Logical session surfaces hosted by the one native WorkspaceScreen."""
from textual.containers import Vertical
from textual.widget import Widget
from textual.reactive import reactive
from toad.widgets.side_bar import SidebarFocusOwner
from pathlib import Path
from typing import TYPE_CHECKING
from toad.project_path_owner import ProjectPathOwner

if TYPE_CHECKING:
    from toad.agent_schema import AgentDefinition
    from toad.screens.main import MainScreen


class SessionOrigin:
    """A view sessions and histories are opened from: it names their agent, project and bus sender."""

    _agent: "AgentDefinition | None"
    _comms_thread: str

    @property
    def origin(self) -> "SessionOrigin":
        return self

    def has_agent(self) -> bool:
        return self._agent is not None

    def spawn(self, *, project: Path | None = None, session_id: str | None = None,
              root: str | None = None) -> "MainScreen":
        """Create a session of this view's agent, on its project unless another is named."""
        from toad.screens.main import MainScreen

        with self.app._context():
            peer = MainScreen(project or self.project_path, self._agent, agent_session_id=session_id)
        peer.initial_coordination_root = root
        return peer


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

    @property
    def origin(self) -> SessionOrigin | None:
        """What a session or history requested from this view starts from."""
        return None

    def belongs_to_wire(self, root) -> bool:
        """Unbound views may project the selected wire; bound views stay on it."""
        from pathlib import Path
        source = self.coordination_root
        return source is None or Path(source).expanduser().resolve() == root

    def sidebar_focus_target(self) -> Widget | None:
        return None

    def sidebars(self):
        """Supply this view's native sidebar resources through its declaration."""
        return ()

    def channels_context(self) -> tuple[str, str]:
        return "", ""

    @property
    def navigation_target_name(self) -> str | None:
        """The displayed destination, independent of sidebar click intent."""
        return None

    def relationship_context(self) -> tuple[str, str | None]:
        return self.channels_context()[0], self.coordination_root

    def activate_session(self) -> None:
        """Bind surface-local observers before its selected frame."""

    async def prepare_navigation(self) -> bool:
        """Reconcile only this logical source's sidebar navigation and observers."""
        from toad.widgets.side_bar import SideBarCollapsible

        changed = False
        for sidebar in self.sidebars():
            panels = tuple(sidebar.query(SideBarCollapsible))
            before = tuple(panel.collapsed for panel in panels)
            changed |= sidebar.restore_navigation()
            changed |= before != tuple(panel.collapsed for panel in panels)
            sidebar.schedule_hydration()
        return changed

    async def prepare_presentation(self) -> None:
        """Restore source-bound rich presentation for the selected logical view."""
        from toad.widgets.history_anchor import HistoryWindow

        for window in self.query(HistoryWindow):
            window.request_preparation()

    async def retire_presentation(self) -> None:
        """Release rich presentation without stopping its operational sources."""
        from toad.widgets.history_anchor import HistoryWindow

        # Specialized source owners capture their reader before entering this
        # shared retirement. Clear its focus before hiding any native resource;
        # shared chrome retains its independently owned focus.
        if self.has_focus_within:
            self.screen.set_focus(None)
        for window in self.query(HistoryWindow):
            window.retire_presentation_wait()
            window.settle_preparation()

    async def close_presentation(self) -> None:
        """Views without retained operational sources need no domain finalization."""

    def retained_native_presentations(self):
        """Declare admitted native trees; non-native views own no such trees."""
        return ()

