"""Session side panels retain reader position while their view is parked."""
from typing import TYPE_CHECKING
from weakref import ref
from textual.app import ComposeResult
from textual.worker import WorkerCancelled
from toad.plan import PlanItem
from toad.widgets.side_bar import ThreadSidebar
from toad.widgets.session_thread_panels import PlanSessionPanel, SessionPanel

if TYPE_CHECKING:
    from toad.screens.main import MainScreen


class SessionThreadSidebar(ThreadSidebar):
    """Keep warm panels until eviction releases their widgets."""

    # Panels retain widgets, not separate transcript sources or paint assets.
    retained_source_bytes = 0
    retained_paint_bytes = 0

    def __init__(self, screen: "MainScreen") -> None:
        self._owner = ref(screen)
        self._panel_owners = tuple(member() for member in SessionPanel.members_with(SessionPanel))
        self.plan = next(owner for owner in self._panel_owners if isinstance(owner, PlanSessionPanel))
        super().__init__(state=screen._thread_sidebar_state, defer_mount=True)

    @property
    def retained_widget_count(self) -> int:
        return 1 + self.descendant_count if self.panels_loaded else 0

    def schedule_hydration(self) -> None:
        if not self.collapsed:
            if not self.panels_loaded:
                self._panels_ready.clear()
            super().schedule_hydration()
        else:
            self._panels_ready.set()

    def _start_hydration(self) -> None:
        if not self.collapsed:
            super()._start_hydration()
        else:
            self._panels_ready.set()

    async def prepare_presentation(self) -> None:
        self.schedule_hydration()

    async def _cancel_panel_workers(self) -> None:
        for worker in self.workers.cancel_group(self, self.PANEL_WORKER_GROUP):
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    async def retire_presentation(self, screen: "MainScreen") -> None:
        if not self.panels_loaded:
            # A partial mount is discarded rather than parked as a complete view.
            await self.evict(screen)
            return
        await self._cancel_panel_workers()
        for panel in self.panels:
            panel.widget.sidebar_visibility_changed()

    async def evict(self, screen: "MainScreen") -> None:
        """Release panels on eviction or close, preserving their reader position."""
        await self._cancel_panel_workers()
        self.navigation.panel_scroll_y = self.panels_viewport.scroll_y
        self.capture_panels(screen)
        await self.panels_viewport.remove_children()
        if controls := self.query_one_optional("#sidebar-controls"):
            await controls.remove_children()
        self.panels.clear()
        self._panels_loaded = self._panels_loading = False
        self._presented_layout = None
        self._panels_ready.set()

    async def panels_hydrated(self) -> None:
        screen = self._owner()
        self.plan.update(self, self.plan.entries)
        self.call_after_refresh(self.panels_viewport.scroll_to, y=self.navigation.panel_scroll_y,
                                animate=False, immediate=True)
        if screen is not None:
            await screen.app.workspace_chrome.native.reconcile(screen)

    def update_plan(self, entries: list[PlanItem]) -> None:
        """Absent panels consume the latest source value, never a replay buffer."""
        self.plan.update(self, entries)

    def capture_panels(self, screen: "MainScreen") -> None:
        for owner, panel in zip(self._panel_owners, self.panels):
            owner.capture(panel.widget)
        screen._project_panel = None

    def _compose_panels(self) -> ComposeResult:
        if not self.panels:
            screen = self._owner()
            if screen is None:
                raise ReferenceError("The session sidebar owner has retired")
            self.panels.extend(owner.compose_panel(screen) for owner in self._panel_owners)
        yield from super()._compose_panels()
