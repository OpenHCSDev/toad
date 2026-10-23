"""The pager's source-owned read, lookahead and retirement lifetime."""
from __future__ import annotations

from collections import deque
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING

from textual.await_complete import AwaitComplete
from textual.worker import Worker, WorkerCancelled

from toad.core.source_events import TranscriptSourceWorkFinished
from toad.core_event_carrier import CoreEventReceiver
from toad.resource_release import ResourceRelease
from toad.transcript_preparation import PreparedPageSource, PreparedTranscriptPage
from toad.transcript_state import (
    LatestViewportRequest,
    LatestViewportState,
    LiveTranscript,
    NoLatestRequest,
    ParkedSourceTranscript,
    RetiredSourceTranscript,
    TranscriptState,
    WorkingTranscript,
)
from toad.widgets.history_anchor import (
    HeldReaderDestination,
    HistoryWindow,
    LatestPosition,
)
from toad.widgets.presentation_window import NEWER_END, OLDER_END, PageEnd, PageRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.screen import Screen

    from toad.transcript_filter import FilterState
    from toad.widgets.transcript_history import TranscriptPageView


class _DrawingStopped(Exception):
    """Unwind a source publication that no longer owns its drawing."""


@dataclass(frozen=True)
class HistorySourceSnapshot:
    """One source/view identity for page and filter publication."""

    generation: int
    window: HistoryWindow
    screen: Screen
    source: object

    def current(self, owner: TranscriptSourcePreparation) -> bool:
        if not owner.can_draw_on_screen:
            return False
        return self == owner.source_snapshot()


class TranscriptSourcePreparation(CoreEventReceiver):
    """Shared source preparation; native widget and operational session stay separate."""


    pages: deque[TranscriptPageView]
    _source_state: TranscriptState
    filter: FilterState

    @classmethod
    def initial_state(cls, view) -> TranscriptState:
        return LiveTranscript()

    @property
    def window(self) -> HistoryWindow:
        return self.query_ancestor(HistoryWindow)

    def __init__(self, *args, source_state: TranscriptState, page_source: PreparedPageSource, **kwargs):
        self._source_state = source_state
        self._generation = 0
        self.page_source = page_source
        self._source_observation = ResourceRelease()
        self.latest: LatestViewportState = NoLatestRequest()
        super().__init__(*args, **kwargs)

    @property
    def state(self) -> TranscriptState:
        return self._source_state.observed(self)

    def rows_published(self) -> None:
        """Admit source rows and withdraw their live predecessors before yielding."""
        self._source_state.rows_published(self)
        for page in self.pages:
            page.display = True

    @property
    def can_draw_on_screen(self) -> bool:
        if not self.state.can_draw:
            return False
        return self.screen.is_current

    def _require_can_draw(self) -> None:
        if not self.state.can_draw:
            raise _DrawingStopped

    def source_snapshot(self) -> HistorySourceSnapshot:
        return HistorySourceSnapshot(self._generation, self.window, self.screen,
                                     self.source_identity)

    @property
    def blocks_visible_read(self) -> bool:
        """Source mutation, remaining tail and filtering govern acknowledgement."""
        return self.state.blocks_visible_read(self)

    @property
    def source_ready(self) -> bool:
        return self.state.source_ready(self)

    def reserve_source_work(self, operation=None) -> WorkingTranscript:
        operation = self._source_state.reserve(self, operation)
        self._source_state = operation
        return operation

    def schedule_source_work(self, work) -> Worker | None:
        """Own source I/O on the pager worker, never its caller's event pump."""
        if self.state.accepts_source_work:
            return self.reserve_source_work().schedule(self, work)

    def source_failed(self, error) -> None:
        from toad import paths

        self.retire_source()
        paths.save_traceback(error, "History_failure")
        self.app.show_error(error, "History")

    def observe_source(self) -> None:
        self.window.histories.add(self)
        self.request_preparation()

    async def on_unmount(self) -> None:
        self._source_observation.close()
        # Parked preparation belongs to the logical document. Unmount revokes
        # this publisher, not the source scope transferred with it.
        self._source_state.retire_preparation(self)
        self._source_state = RetiredSourceTranscript(self._source_state.retirement_source())
        self._generation += 1
        self.window.histories.discard(self)
        await self.close_source_reader()

    def close(self) -> None:
        from toad.transcript_preparation import ClosedHistory

        source = self.page_source
        source.close()
        self.page_source = ClosedHistory(source.through, source.runtime)

    async def close_source_reader(self) -> None:
        """Close source subscriptions without releasing the separately held pages."""

    def request_preparation(self) -> None:
        """Use the frame's preparation slot for this independent source.

        The window supplies scroll/layout demand. A pager keeps its own native
        callback scope so a held sibling cannot block its source publication.
        The frame owns deduplication, including work requested during I/O.
        """
        if self.can_draw_on_screen:
            self.screen.frame_presentation.defer(self, self.prepare_viewport)

    def prepare_viewport(self) -> None:
        """Consume committed geometry once, on this source's own pump."""
        if self.can_draw_on_screen:
            self.latest = self.latest.resume(self)
            for page in self.visible_pages():
                page.prepare_viewport(self.window)
            self.state.check_edges(self)

    def request_page(self, end) -> None:
        self.schedule_source_work(partial(self._prepare_edge, end))

    @property
    def follows_source_tail(self) -> bool:
        return self.window.follows_tail

    def has_more(self, end: PageEnd) -> bool:
        page = end.edge(self.pages).prepared
        return end.can_extend(page) or self.page_source.has_more(end, page.page)

    async def _prepare_edge(self, end) -> None:
        """Keep one preparation slot while committed publications request more rows."""
        snapshot = self.source_snapshot()
        while snapshot.current(self) and await self._load_page(end):
            pass

    async def _load_page(self, end) -> bool:
        """Publish one source range; return whether this edge still needs rows."""
        raise NotImplementedError

    def request_latest(self, destination: LatestPosition) -> None:
        # End supersedes any admitted edge publication. Its worker may finish
        # the source read, but the old snapshot cannot paint an intermediate page.
        self._generation += 1
        self.state.request_latest(self, LatestViewportRequest(destination))

    async def jump_latest(self, request: LatestViewportRequest,
                           publication_current: Callable[[], bool] = lambda: True) -> bool:
        """Publish one destination using its captured source and reader position.

        A preceding page's restoration may have left the window off its tail.
        Apply the still-current destination before its source read, then finish
        native geometry after publication. Neither restoration is another user
        scroll; movement during I/O invalidates the captured request revision.
        """
        if not request.current(self.window):
            return False
        if not self.can_draw_on_screen:
            self.latest = request.defer(self)
            return False
        request.restore(self.window)
        snapshot = self.source_snapshot()
        current = lambda: snapshot.current(self) and request.current(snapshot.window) and publication_current()
        with request.reading(self) as (source, release):
            prepared = await request.page(self, source)
            if await self._publish_latest(current, source, prepared, release):
                # Capture the source accepted with the destination's pages.
                self.call_after_refresh(self._complete_latest, self.source_snapshot(), request)
                return True
        self.latest = request.defer(self)
        return False

    async def _publish_latest(self, current: Callable[[], bool],
                              source: PreparedPageSource, prepared: PreparedTranscriptPage,
                              release: ResourceRelease) -> bool:
        """Prepare the bottom destination, keeping views of unchanged source pages."""
        window = self.window
        edge = self.pages[-1]
        latest = prepared
        rows, limit = window.latest_limits(self.budget)
        pages_read = 1
        destination: list[tuple[PreparedTranscriptPage, TranscriptPageView | None]] = []
        while rows > 0 and limit > 0:
            existing = next((view for view in self.pages
                             if view.prepared.same_source(prepared)), None)
            if existing is not None:
                prepared = existing.prepared.for_view()
            rows -= await prepared.prepare_rows(
                self, current, target=self, selected=self.selected_categories,
                boundary=len(prepared.fragments), end=OLDER_END,
                rows_needed=rows, limit=limit,
            )
            if not current():
                return False
            take = prepared.stop - prepared.start
            if take:
                destination.insert(0, (prepared, existing))
            limit -= take
            if rows <= 0:
                break
            if (not source.has_older(prepared.page) or limit <= 0
                    or not window.presentation_budget.can_read_destination(pages_read)):
                break
            prepared = (await source.get(OLDER_END.adjacent(prepared.page))).for_view()
            pages_read += 1
        async with window.history_lock:
            if not current() or self.pages[-1] is not edge:
                return False
            async with window.preserve_history(root=self):
                previous = tuple(self.pages)
                views = deque()
                if not destination:
                    # An empty answer is published too: the edge draws nothing,
                    # at its end. `latest` was never ranged by the loop above.
                    latest.set_fragment_range(slice(len(latest.fragments), len(latest.fragments)))
                    destination.append((latest, None))
                try:
                    async with AsyncExitStack() as acquisition:
                        for prepared, view in reversed(destination):
                            if view is None:
                                view = await acquisition.enter_async_context(type(edge).acquire(
                                    self, prepared, end=OLDER_END, pages=views, current=current,
                                ))
                            views.appendleft(view)
                        # Keep existing fragments, prepared lines and documents.
                        for prepared, view in destination:
                            if view is not None and not view.prepared.replace_range(
                                view, slice(prepared.start, prepared.stop), current,
                            ):
                                raise _DrawingStopped
                        previous_source = self.page_source
                        self.page_source, self.pages = source, views
                        source.through = latest.page.after
                        release.pop_all()
                        if previous_source is not source:
                            release.callback(previous_source.close)
                            self.filter = self.filter.changed()
                except _DrawingStopped:
                    return False
                retired = tuple(page for page in previous if page not in views)
                for page in retired:
                    page.display = False
                self._update_edges()
                self.rows_published()
                await self.remove_children(retired)
            return True

    @property
    def drawn_end_more(self) -> bool:
        """Rows below the drawn end that the reader was already shown exist: prepared ones, or a known newer page.

        Source rows a commit adds beyond the drawn end are not among them; they arrive.
        """
        edge = self.pages[-1].prepared
        return NEWER_END.can_extend(edge) or edge.page.has_newer

    async def extend(self, through, publication_current: Callable[[], bool] = lambda: True) -> bool:
        """Append to a complete followed tail; a gap uses the bounded latest read."""
        if not publication_current():
            return False
        self.page_source.through = through
        edge = self.pages[-1]
        if edge.prepared.page.after == self.page_source.through:
            return True
        if self.drawn_end_more:
            destination = HeldReaderDestination.held(self.window)
            if destination is not None and await destination.source_arrived(self):
                return True
            if not edge.prepared.page.has_newer:
                edge.prepared.page = replace(edge.prepared.page, has_newer=True)
            return True
        snapshot = self.source_snapshot()
        prepared = await self.page_source.get(NEWER_END.adjacent(edge.prepared.page))
        if not await self.source_is_current(snapshot) or not publication_current():
            return False
        if self.pages[-1] is not edge:
            return False
        if not await self.page_source.accept_page(self, edge, prepared):
            return False
        if not prepared.fragments:
            NEWER_END.advance_empty(edge.prepared, prepared)
        elif not self.window.follows_tail:
            edge.prepared.page = replace(edge.prepared.page, has_newer=True)
            self._update_edges()
        else:
            await self._load_page(NEWER_END, publication_current)
            if not snapshot.current(self) or not publication_current():
                return False
            tail = self.pages[-1]
            if tail.prepared.page.after != self.page_source.through:
                # Rejected preparation still leaves the source gap reachable.
                tail.prepared.page = replace(tail.prepared.page, has_newer=True)
                self._update_edges()
            if self.pages[-1].prepared.page.has_newer and self.window.follows_tail:
                await self.jump_latest(
                    LatestViewportRequest(LatestPosition.hold(self.window)), publication_current,
                )
        return True

    async def source_is_current(self, snapshot) -> bool:
        return snapshot.current(self)

    def _complete_latest(
        self, snapshot: HistorySourceSnapshot, request: LatestViewportRequest,
    ) -> None:
        if snapshot.current(self):
            request.restore(snapshot.window)
            request.destination.source_settled(snapshot.window)
            snapshot.window.lookahead.destination_complete()

    def supersede_source_work(
        self, operation: WorkingTranscript, request: LatestViewportRequest,
    ) -> None:
        """Replace an edge read with End's destination without publishing it."""
        if self._source_state is not operation:
            return
        self._source_observation.close()
        self._source_state = operation.source
        self.workers.cancel_node(self)
        request.apply(self)

    def finish_source_work(self, operation: WorkingTranscript) -> None:
        # Only the current operation may publish. A cancelled
        # old operation cannot publish again or settle a newer source's work.
        if self._source_state is operation:
            self._source_observation.close()
            self._source_state = operation.source
            if self.state.can_draw:
                self.window.check_follow()
                # The admitted operation owns source and reader progress.
                # Native compensation and unchanged reads cannot rearm it.
                if operation.progressed(self):
                    self.request_preparation()
                self.latest.prepare(self)
                self.publish_core(TranscriptSourceWorkFinished())
                HeldReaderDestination.settle(self.window)

    def retire_source(self, *, parked: bool = False) -> AwaitComplete:
        """Withdraw publication now; join its cancelled work independently."""
        self._source_observation.close()
        source = self._source_state.retirement_source()
        self._source_state = (ParkedSourceTranscript(source) if parked
                              else RetiredSourceTranscript(source))
        self._generation += 1
        if self.is_attached:
            self.window.histories.discard(self)
        self._source_state.retire_preparation(self)
        workers = self.workers.cancel_node(self)

        async def join():
            for worker in workers:
                try:
                    await worker.wait()
                except WorkerCancelled:
                    pass

        return AwaitComplete(join())

    def resume_source(self) -> None:
        self._source_state = self._source_state.resume()
        self.window.histories.add(self)
        self.source_resumed()
        self.window.check_follow()
        self.request_preparation()


    @property
    def drawn_extent(self) -> tuple[int, int]:
        """Rows drawn and the source items they show, for converting rows to items."""
        raise NotImplementedError

    def source_resumed(self) -> None:
        """A parked source publishes again: report what its drawn pages mean to their owner."""
        raise NotImplementedError
