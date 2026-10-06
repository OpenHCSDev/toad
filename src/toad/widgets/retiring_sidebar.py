"""Optional sidebar content uses the workspace's existing admission lifetime."""
from textual.worker import WorkerCancelled
from toad.widgets.side_bar import CommsSideBar
from toad.widgets.side_bar import SideBarCollapsible, SidebarVisibilityObserver
from toad.widgets.sidebar_viewport import SidebarViewport


class RetiringSidebar(CommsSideBar):
    """Park admitted panel resources; eviction retains only reader intent."""

    @property
    def retained_widget_count(self) -> int:
        return 1 + self.descendant_count if self._panels_loaded else 0

    @property
    def retained_source_bytes(self) -> int:
        # This panel graph holds no transcript page/source asset.
        return 0

    @property
    def retained_paint_bytes(self) -> int:
        # Panel paint stays widget-owned and participates through widget cost.
        return 0

    def schedule_hydration(self) -> None:
        if not self.collapsed:
            if not self._panels_loaded:
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

    async def retire_presentation(self) -> None:
        for worker in self.workers.cancel_group(self, "sidebar-panels"):
            try:
                await worker.wait()
            except WorkerCancelled:
                pass
        if not self._panels_loaded:
            # A cancelled partial mount was never a complete admitted panel set.
            await self.evict()
        else:
            for panel in self.panels:
                if isinstance(panel.widget, SidebarVisibilityObserver):
                    panel.widget.sidebar_visibility_changed()

    async def evict(self) -> None:
        """The session resource owner releases panels at actual eviction/close."""
        for worker in self.workers.cancel_group(self, "sidebar-panels"):
            try:
                await worker.wait()
            except WorkerCancelled:
                pass
        viewport = self.query_one("#sidebar-panels", SidebarViewport)
        self.navigation.panel_scroll_y = viewport.scroll_y
        for panel in self.query(SideBarCollapsible):
            self.navigation.panels_collapsed[str(panel.title)] = panel.collapsed
        self.capture_panels()
        await viewport.remove_children()
        if controls := self.query_one_optional("#sidebar-controls"):
            await controls.remove_children()
        self.panels.clear()
        self._panels_loaded = self._panels_loading = False
        self._presented_layout = None
        self._panels_ready.set()

    def capture_panels(self) -> None:
        """Each declaration captures only its original reader intent."""
        raise NotImplementedError
