"""The pager's source-owned read, lookahead and retirement lifetime."""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from textual.worker import Worker, WorkerCancelled
from toad.core_event_carrier import CoreEventReceiver
from toad.transcript_state import TranscriptState, RetiredSourceTranscript, ParkedSourceTranscript, WorkingTranscript, LatestViewportRequest
from toad.transcript_preparation import PreparedPageSource
from toad.core.source_events import TranscriptSourceWorkFinished

if TYPE_CHECKING:
    from collections.abc import Callable
    from textual.screen import Screen
    from toad.widgets.history_anchor import HistoryWindow


@dataclass(frozen=True)
class HistorySourceSnapshot:
    """One original source/view identity for page and filter publication."""

    generation: int
    window: HistoryWindow
    screen: Screen
    source: object

    def current(self, owner: TranscriptSourcePreparation) -> bool:
        if not owner.source_publication_available:
            return False
        return self == owner.source_snapshot()


class TranscriptSourcePreparation(CoreEventReceiver):
    """Shared source preparation; native widget and operational session stay separate."""

    def __init__(self, *args, source_state: TranscriptState, **kwargs):
        self._source_state = source_state
        self._generation = 0
        self._page_buffer: PreparedPageSource | None = None
        self._prefetch_worker = None
        self._prefetch_intent = None
        self._check_pending = False
        super().__init__(*args, **kwargs)

    @property
    def state(self) -> TranscriptState:
        return self._source_state.observed(self)

    @property
    def source_publication_available(self) -> bool:
        if not self.state.accepts_publication:
            return False
        return self.screen.is_current

    def source_snapshot(self) -> HistorySourceSnapshot:
        return HistorySourceSnapshot(self._generation, self.window, self.screen,
                                     self.source_identity)

    @property
    def blocks_visible_read(self) -> bool:
        """Source mutation, remaining tail and filtering govern acknowledgement."""
        return self.state.blocks_visible_read(self)

    @property
    def checkpoint_available(self) -> bool:
        return self.state.checkpoint_available(self)

    def reserve_source_work(self) -> WorkingTranscript:
        operation = self._source_state.reserve(self)
        self._source_state = operation
        return operation

    def schedule_source_work(self, work) -> Worker | None:
        """Own source I/O on the pager worker, never its caller's event pump."""
        if self.state.accepts_source_work:
            return self.reserve_source_work().schedule(self, work)

    def source_failed(self, error) -> None:
        self.notify(str(error), title="History", severity="error")

    def observe_source(self) -> None:
        self.window.histories.add(self)
        self.watch(self.window, "scroll_y", self._scroll_changed, init=False)
        self.screen.screen_layout_refresh_signal.subscribe(self, self._layout_changed)
        self._scroll_changed()
        self.prepare_scroll()

    async def on_unmount(self) -> None:
        self._source_state = RetiredSourceTranscript(self._source_state.retirement_source())
        self._generation += 1
        self._prefetch_intent = None
        self.window.histories.discard(self)
        if self._page_buffer is not None:
            self._page_buffer.close()
        await self.close_source_reader()

    async def close_source_reader(self) -> None:
        """Native prepared-page scope is closed by the common lifetime."""

    def _layout_changed(self, _screen) -> None:
        self._scroll_changed()
        self.prepare_scroll()

    def on_resize(self) -> None:
        if self.is_mounted:
            self._scroll_changed()

    def _scroll_changed(self, _y: float = 0) -> None:
        if self.state.accepts_source_work and not self._check_pending:
            self._check_pending = True
            self.call_after_refresh(self._check_edges)

    def _request_page(self, older: bool) -> None:
        self.schedule_source_work(partial(self._load_page, older))

    def request_latest(self) -> None:
        self.window.document_viewport.destination()
        if self._prefetch_worker is not None:
            self._prefetch_worker.cancel()
        self._prefetch_intent = None
        self.state.request_latest(self, LatestViewportRequest(self.window.scroll_revision))

    async def _jump_latest(self, request: LatestViewportRequest) -> None:
        """Publish one destination under its original source and reader intent.

        A preceding page's restoration may have left the window off its tail.
        Apply the still-current destination before its source read, then finish
        native geometry after publication. Neither restoration is another user
        scroll; movement during I/O revokes this request at its original revision.
        """
        if not self.source_publication_available or not request.current(self.window):
            return
        self._generation += 1
        request.restore(self.window)
        if await self._publish_latest(request):
            # Wire acceptance advances the original reader source. Capture the
            # published source, rather than the request that acceptance replaced.
            self.call_after_refresh(self._complete_latest, self.source_snapshot(), request)

    async def _publish_latest(self, request: LatestViewportRequest) -> bool:
        """The source leaf reads/prepares and fences its original publication."""
        raise NotImplementedError

    def _complete_latest(
        self, snapshot: HistorySourceSnapshot, request: LatestViewportRequest,
    ) -> None:
        if snapshot.current(self):
            request.restore(snapshot.window)

    def defer_source_work(self, operation: WorkingTranscript, work) -> None:
        """Keep the original read until the shared observer supplies relief.

        This signal subscription is an operation resource. Its original source
        snapshot rejects a replaced, parked or retired pager before admission.
        """
        snapshot = self.source_snapshot()

        def resume(_event) -> None:
            self.retire_core_observations(self.app.coordination_access.events)
            if snapshot.current(self) and self._source_state is operation:
                operation.schedule(self, work)
            else:
                self.finish_source_work(operation)

        self.retire_core_observations(self.app.coordination_access.events)
        self.observe_core_callback(self.app.coordination_access.events, resume)

    def finish_source_work(self, operation: WorkingTranscript) -> None:
        # Retirement or replacement revokes this exact admission. A cancelled
        # old operation cannot publish again or settle a newer source's work.
        if self._source_state is operation:
            self._source_state = operation.source
            operation.pending_request.apply(self)
            if self.state.accepts_publication:
                self.window.check_follow()
                # The admitted operation owns source and reader progress.
                # Native compensation and unchanged reads cannot rearm it.
                if operation.progressed(self):
                    self._scroll_changed()
                self.publish_core(TranscriptSourceWorkFinished())

    async def retire_source(self, *, parked: bool = False) -> None:
        """End pager mutations before any of its bodies transfer to the shelf."""
        self.retire_core_observations(self.app.coordination_access.events)
        source = self._source_state.retirement_source()
        self._source_state = (ParkedSourceTranscript(source) if parked
                              else RetiredSourceTranscript(source))
        self._generation += 1
        self._prefetch_intent = None
        self.window.histories.discard(self)
        self._source_state.retire_preparation(self._page_buffer)
        for worker in self.workers.cancel_node(self):
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    def resume_source(self) -> None:
        self._source_state = self._source_state.resume()
        self._prefetch_intent = None
        self.window.histories.add(self)
        self.report_source_coverage()
        self.window.check_follow()
        self._scroll_changed()
        self.prepare_scroll()


    def prepare_scroll(self) -> None:
        """Measured viewport demand admits source-specific edge reads."""
        self._scroll_changed()

    def request_lookahead(self, intent) -> None:
        """One source worker consumes the latest measured preparation demand.

        Updating the requested extent does not revoke an admitted pure batch.
        The source leaf checks its original source, page and direction custody;
        after that pass this worker takes the latest intent, without restarting
        its waiter on every scroll or layout publication.
        """
        if intent == self._prefetch_intent:
            return
        previous = self._prefetch_intent
        self._prefetch_intent = intent
        if self._prefetch_worker is not None and not self._prefetch_worker.is_finished:
            if previous is not None and self.lookahead_current(previous):
                return
            self._prefetch_worker.cancel()

        async def prepare() -> None:
            while (intent := self._prefetch_intent) is not None:
                await self.prepare_lookahead(intent)
                if self._prefetch_intent is intent:
                    return

        self._prefetch_worker = self.run_worker(prepare, group="history-lookahead", exit_on_error=False)

    async def prepare_lookahead(self, intent) -> None:
        """The prepared source leaf supplies its bounded page/body work."""
        raise NotImplementedError

    def lookahead_current(self, intent) -> bool:
        """Source, page and direction custody revoke an obsolete waiter."""
        raise NotImplementedError

    @property
    def prefetch_distance(self) -> int:
        """Start background reads before the earlier edge enters the viewport."""
        rows = self.window.size.height
        return self.window.document_viewport.lookahead.ahead_rows(rows)
