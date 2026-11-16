"""The pager's source-owned read, lookahead and retirement lifetime."""

from contextvars import Context

from textual import on
from textual.await_complete import AwaitComplete
from textual.events import Unmount
from textual.worker import WorkerCancelled

from toad.core_event_carrier import CoreEventReceiver
from toad.client.history_pager import HistoryPager
from toad.frame_presentation import UnrisenRows
from toad.client.history_state import (
    RetiredSourceTranscript,
)
from toad.widgets.history_anchor import HistoryWindow
from toad.client.history_preparation import (
    HistorySourceSnapshot,
)


class TranscriptSourcePreparation(HistoryPager, UnrisenRows, CoreEventReceiver):
    """Shared source preparation; native widget and operational session stay separate.

    A pager can hold arriving rows below a following reader (`UnrisenRows`); one whose
    rows never cascade holds none, which is that contract's default.
    """

    @property
    def window(self) -> HistoryWindow:
        return self.query_ancestor(HistoryWindow)


    @property
    def can_draw_on_screen(self) -> bool:
        if not self.state.can_draw:
            return False
        return self.screen.is_current

    def source_snapshot(self) -> HistorySourceSnapshot:
        return HistorySourceSnapshot(self._generation, self.window, self.screen,
                                     self.source_identity)


    def followed_here(self) -> None:
        """Register with the window drawing these pages, and keep it: it needs this pager in
        its tail arithmetic, and this pager needs it to move the reader as rows rise. One
        call, so a holder is never in the sum without being able to move the reader."""
        window = self.window
        window.histories.add(self)
        self.followed_by(window)

    @on(Unmount)
    async def on_unmount(self) -> None:
        self._source_observation.close()
        # Parked preparation belongs to the logical document. Unmount revokes
        # this publisher, not the source scope transferred with it.
        self._source_state.retire_preparation(self)
        self._source_state = RetiredSourceTranscript(self._source_state.retirement_source())
        self._generation += 1
        self.window.histories.discard(self)
        await self.close_source_reader()

    def request_preparation(self) -> None:
        """Use the frame's preparation slot for this independent source.

        The window supplies scroll/layout demand. A pager keeps its own native
        callback scope so a held sibling cannot block its source publication.
        The frame owns deduplication, including work requested during I/O.
        """
        if self.can_draw_on_screen:
            self.screen.frame_presentation.defer(self, self.prepare_viewport)


    def prepare_visible_pages(self) -> None:
        for page in self.visible_pages():
            page.prepare_viewport(self.window)

    def cancel_work(self) -> list:
        return self.workers.cancel_node(self)

    def joined(self, workers: list) -> AwaitComplete:
        async def join():
            for worker in workers:
                try:
                    await worker.wait()
                except WorkerCancelled:
                    pass

        # The join owns only the cancelled Worker handles, not the caller's
        # worker or message pump. AwaitComplete eagerly schedules its coroutine;
        # inheriting a failed pager's active_worker makes Worker.wait reject this
        # independent join as a self-wait.
        return Context().run(AwaitComplete, join())
