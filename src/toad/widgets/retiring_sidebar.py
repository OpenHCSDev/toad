"""Optional sidebar content uses the workspace's existing admission lifetime."""
from abc import ABC, abstractmethod
from textual.worker import WorkerCancelled
from toad.widgets.side_bar import SideBar
from toad.widgets.sidebar_viewport import SidebarViewport


class RetiringSidebar(SideBar, ABC):
    """Retain reader intent, never an inactive panel widget graph."""

    def schedule_hydration(self) -> None:
        if not self.collapsed:
            if not self._panels_loaded:
                self._panels_ready.clear()
            super().schedule_hydration()

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
        viewport = self.query_one("#sidebar-panels", SidebarViewport)
        self.navigation.panel_scroll_y = viewport.scroll_y
        self.capture_panels()
        await viewport.remove_children()
        if controls := self.query_one_optional("#sidebar-controls"):
            await controls.remove_children()
        self.panels.clear()
        self._panels_loaded = self._panels_loading = False
        self._presented_layout = None
        self._panels_ready.set()

    @abstractmethod
    def capture_panels(self) -> None:
        """Each declaration captures only its original reader intent."""
