"""The pager's source-owned read, lookahead and retirement lifetime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.worker import WorkerCancelled
from textual.message import Message
from toad.transcript_state import TranscriptState, RetiredSourceTranscript, ParkedSourceTranscript, WorkingTranscript
from toad.transcript_preparation import PreparedPageSource, TranscriptPageBuffer
from toad.widgets.committed_presentation import TranscriptCoverage

if TYPE_CHECKING:
    from collections.abc import Callable
    from textual.screen import Screen
    from toad.widgets.conversation import Window
    from toad.widgets.message_filter import MessageCategory
    from toad.widgets.transcript_history import TranscriptHistory


@dataclass(frozen=True)
class HistorySourceSnapshot:
    """One original source/view identity for page and filter publication."""

    generation: int
    selected: frozenset[type[MessageCategory]]
    window: Window
    loader: Callable | None
    screen: Screen

    def current(self, owner: TranscriptHistory) -> bool:
        if not owner.source_publication_available:
            return False
        return self == owner.source_snapshot()


class TranscriptSourceWorkFinished(Message):
    """The original pager released its admitted mutation resource."""

    def __init__(self, history):
        super().__init__()
        self.history = history


class TranscriptSourcePreparation:
    """Shared source preparation; native widget and operational session stay separate."""

    def __init__(self, *args, source_state: TranscriptState, loader, through, **kwargs):
        self.loader = loader
        self.through = through
        self._source_state = source_state
        self._generation = 0
        self._page_buffer: PreparedPageSource | None = None
        self._prefetch_worker = None
        self._prefetch_intent = None
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
        return HistorySourceSnapshot(self._generation, self.selected_categories,
                                     self.window, self.loader, self.screen)

    @property
    def blocks_visible_read(self) -> bool:
        """Source mutation, remaining tail and filtering govern acknowledgement."""
        return self.is_attached and (self.has_newer or not self.checkpoint_available)

    def reserve_source_work(self) -> WorkingTranscript:
        operation = self._source_state.reserve()
        self._source_state = operation
        return operation

    def finish_source_work(self, operation: WorkingTranscript) -> None:
        # Retirement or replacement revokes this exact admission. A cancelled
        # old operation cannot publish again or settle a newer source's work.
        if self._source_state is operation:
            self._source_state = operation.source
            operation.pending_request.apply(self)
            if self.state.accepts_publication:
                self.window.check_follow()
                self._scroll_changed()
                self.post_message(TranscriptSourceWorkFinished(self))

    async def retire_source(self, *, parked: bool = False) -> None:
        """End pager mutations before any of its bodies transfer to the shelf."""
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
        if self._source_state.reports_coverage:
            self.post_message(TranscriptCoverage(tuple(self.coverage_events), self))
        self.window.check_follow()
        self._scroll_changed()
        self.prepare_scroll()


    def _reader(self) -> PreparedPageSource:
        assert self.loader is not None
        reader = self._page_buffer
        if reader is None or reader.loader is not self.loader or reader.through != self.through:
            if reader is not None:
                reader.close()
            self._page_buffer = reader = TranscriptPageBuffer(
                self.loader, self.through, self.app.preparation,
            )
            self._prefetch_intent = None
        return reader


    def prepare_scroll(self) -> None:
        if (self.loader is None or not self.is_mounted or not self.state.accepts_publication or not self.screen.is_current
                or not self.selected_categories):
            return
        reader = self._reader()
        edges = (self.pages[0].page.before if self.pages[0].page.has_older else None,
                 self.pages[-1].page.after if self.pages[-1].page.has_newer else None)
        lookahead = self.window.document_viewport.lookahead
        demand = lookahead.demand
        edges = demand.edges(*edges)
        rows = max(1, self.window.size.height)
        rounds = min(self.budget.reserve_batches,
                     1 + lookahead.ahead_rows(rows) // rows)
        pages = tuple(dict.fromkeys((self.pages[0], self.pages[-1])))
        admissions = tuple(page.capture_admission() for page in pages)
        intent = edges, rounds, self.selected_categories, demand, admissions
        if intent == self._prefetch_intent:
            return
        self._prefetch_intent = intent
        if self._prefetch_worker is not None and not self._prefetch_worker.is_finished:
            self._prefetch_worker.cancel()

        # Transport completion does not exhaust the current page's local
        # admission. Its unmounted leaves still need the stationary runway;
        # the original reader skips absent transport edges itself.
        if not rounds:
            return

        async def prepare() -> None:
            # Reader replacement and source retirement both revoke this exact
            # intent. One owned snapshot identity is the publication fence.
            current = lambda: (self._prefetch_intent is intent
                               and demand is lookahead.demand)
            from toad.render_tasks import TranscriptBodyPreparation
            preparation = TranscriptBodyPreparation(
                self.app.render_processes, self.app.native_ansi_color, self.app.current_theme.dark,
            )
            # The source page already owns these unmounted leaves. Prepare its
            # actual neighboring range, never another paging cursor or list.
            count = lookahead.admission(self.budget, rows)
            for page in pages:
                await page.prepare_adjacent(preparation, demand, count, current)
            async for prepared in reader.prefetch(*edges, current, rounds=rounds):
                # A fetched page is not mounted yet. Warm the actual incoming
                # edge in the same syntax/fence cache used by its future body.
                fragments = demand.neighbors(prepared.fragments, len(prepared.fragments), 0, count)
                await preparation.prepare_fragments(
                    fragments, current, batch_size=self.budget.admission_items,
                )

        self._prefetch_worker = self.run_worker(prepare, group="history-lookahead", exit_on_error=False)


    @property
    def prefetch_distance(self) -> int:
        """Start background reads before the earlier edge enters the viewport."""
        rows = self.window.size.height
        return self.window.document_viewport.lookahead.ahead_rows(rows)
