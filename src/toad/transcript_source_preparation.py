"""The pager's source-owned read, lookahead and retirement lifetime."""
from textual.worker import WorkerCancelled
from toad.transcript_state import TranscriptState, RetiredSourceTranscript, ParkedSourceTranscript
from toad.transcript_preparation import PreparedPageSource, TranscriptPageBuffer


class TranscriptSourcePreparation:
    """Shared source preparation; native widget and operational session stay separate."""

    def __init__(self, *args, source_state: TranscriptState, loader, through, **kwargs):
        self.loader = loader
        self.through = through
        self._source_state = source_state
        self._generation = 0
        self._page_buffer: PreparedPageSource | None = None
        self._prefetch_worker = None
        self._prefetched_edges = None
        self._prefetch_intent = None
        super().__init__(*args, **kwargs)

    @property
    def state(self) -> TranscriptState:
        return self._source_state.observed(self)

    async def retire_source(self, *, parked: bool = False) -> None:
        """End pager mutations before any of its bodies transfer to the shelf."""
        if not isinstance(self._source_state, ParkedSourceTranscript):
            self._source_state = (ParkedSourceTranscript(self._source_state) if parked
                                  else RetiredSourceTranscript(self._source_state))
        self._generation += 1
        self._prefetch_intent = None
        self.window.histories.discard(self)
        if self._page_buffer is not None:
            self._page_buffer.close()
        for worker in self.workers.cancel_node(self):
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    def resume_source(self) -> None:
        state = self._source_state
        if not isinstance(state, ParkedSourceTranscript):
            raise RuntimeError("Only a parked transcript can resume publication")
        self._source_state = state.resume()
        self._page_buffer = None
        self._prefetched_edges = self._prefetch_intent = None
        self.window.histories.add(self)
        self._scroll_changed()
        self._warm_pages()


    def _reader(self) -> PreparedPageSource:
        assert self.loader is not None
        reader = self._page_buffer
        if reader is None or reader.loader is not self.loader or reader.through != self.through:
            if reader is not None:
                reader.close()
            self._page_buffer = reader = TranscriptPageBuffer(
                self.loader, self.through, self.app.preparation,
            )
            self._prefetched_edges = None
            self._prefetch_intent = None
        return reader


    def _warm_pages(self) -> None:
        if (self.loader is None or not self.is_mounted or not self.state.accepts_publication or not self.screen.is_current
                or not self.selected_categories):
            return
        reader = self._reader()
        edges = (self.pages[0].page.before if self.pages[0].page.has_older else None,
                 self.pages[-1].page.after if self.pages[-1].page.has_newer else None)
        travel = self.window.document_viewport.lookahead.travel_rows
        if travel < 0:
            edges = (edges[0], None)
        elif travel > 0:
            edges = (None, edges[1])
        rounds = 1 + self.window.document_viewport.lookahead.ahead_rows(self.window.size.height) // max(1, self.window.size.height // self.budget.admission_items)
        intent = edges, rounds, self.selected_categories
        if intent == self._prefetch_intent:
            return
        self._prefetch_intent = intent
        if self._prefetch_worker is not None and not self._prefetch_worker.is_finished:
            self._prefetch_worker.cancel()

        async def prepare() -> None:
            # Reader replacement and source retirement both revoke this exact
            # intent. One owned snapshot identity is the publication fence.
            current = lambda: self._prefetch_intent is intent
            if await reader.prefetch(*edges, current, rounds=rounds) and current():
                self._prefetched_edges = edges

        self._prefetch_worker = self.run_worker(prepare(), group="history-lookahead", exit_on_error=False)


    @property
    def prefetch_distance(self) -> int:
        """Start background reads before the earlier edge enters the viewport."""
        rows = self.window.size.height
        return max(4, rows // 2) + self.window.document_viewport.lookahead.ahead_rows(rows)
