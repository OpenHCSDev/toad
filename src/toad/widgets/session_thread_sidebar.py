"""Session-scoped reader intent, with only selected rich panels admitted."""
from typing import TYPE_CHECKING
from weakref import ref
from textual.app import ComposeResult
from toad.widgets.plan import Plan
from toad.widgets.retiring_sidebar import RetiringSidebar
from toad.widgets.session_thread_panels import PlanSessionPanel, SessionPanel
from toad.widgets.sidebar_viewport import SidebarViewport

if TYPE_CHECKING:
    from toad.screens.main import MainScreen


class SessionThreadSidebar(RetiringSidebar):
    """Panel declarations survive retirement; widgets and subscriptions do not."""

    def __init__(self, screen: "MainScreen") -> None:
        self._owner = ref(screen)
        self._panel_owners = tuple(member() for member in SessionPanel.members_with(SessionPanel))
        self.plan = next(owner for owner in self._panel_owners if isinstance(owner, PlanSessionPanel))
        super().__init__(id="thread-sidebar", right=True, hide=True,
                         navigation=screen._thread_sidebar_state,
                         defer_mount=True, on_hydrated=self._sync_hydrated)

    def _sync_hydrated(self) -> None:
        screen = self._owner()
        if screen is not None:
            screen._sync_thread_sidebar()
        self.plan.update(self, self.plan.entries)
        viewport = self.query_one("#sidebar-panels", SidebarViewport)
        self.call_after_refresh(viewport.scroll_to, y=self.navigation.panel_scroll_y,
                                animate=False, immediate=True)

    def update_plan(self, entries: list[Plan.Entry]) -> None:
        """Absent panels consume the latest source value, never a replay buffer."""
        self.plan.update(self, entries)

    def capture_panels(self) -> None:
        for owner, panel in zip(self._panel_owners, self.panels):
            owner.capture(panel.widget)
        screen = self._owner()
        if screen is not None:
            screen._project_panel = None

    def _compose_panels(self) -> ComposeResult:
        if not self.panels:
            screen = self._owner()
            if screen is None:
                raise ReferenceError("The session sidebar owner has retired")
            self.panels.extend(owner.compose_panel(screen) for owner in self._panel_owners)
        yield from super()._compose_panels()
