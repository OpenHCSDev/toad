"""Toolkit-neutral committed-history body: the methods that read coverage, publish
coverage and report the drawn pages. Hoisted out of `widgets/transcript_history.py` so
both Textual's `CommittedHistory` and Qt's `QtTranscriptHistory` share one implementation.

The body uses only toolkit-neutral primitives: `call_after_refresh` (abstract in
`NativePager`; implemented by Textual's Widget and Qt's `QtConversationHistory`),
`request_preparation` (on `HistoryPager`), `publish_core` (abstract stub on `NativePager`),
`self.pages`, `self.filter`, `self._source_state`, `self.page_source`, `self.extend_source`
(all on `HistoryPager`). No `textual.*` imports reach this module.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from agent_comms.acp_extension import InputStartedUpdate
from agent_comms.execution.transcript_sources import TranscriptCursor
from agent_comms.messaging.sent_message import (
    OutgoingMessageReference,
    PublishedSentMessage,
)
from agent_comms.transcript.transcript_events import TranscriptEvent

from toad.client.history_coverage import CoveredHistory, HistoryCoverage
from toad.client.prepared_pages import PreparedPageSource
from toad.client.source_resumption import ResumesSource
from toad.commit_claims import CommitClaim, SnapshotPresentation
from toad.core.source_events import TranscriptCoverage

if TYPE_CHECKING:
    from toad.forms.presentation import EntryPlacement


class CommittedHistoryBase(SnapshotPresentation, ResumesSource, CoveredHistory[PreparedPageSource]):
    """A saved source block that precedes the conversation's live tail. Behaviour-only
    base: both frontends pair this with their own pager/presentation base and let the
    MRO deliver the pager primitives (`call_after_refresh`, `request_preparation`,
    `publish_core`, `self.pages`, `self.filter`, `self._source_state`, `self.page_source`,
    `self.extend_source`)."""

    conversation_order = 0

    def prepare_post(self, placement: EntryPlacement) -> None:
        self.conversation_order = placement.live_order - 1

    @property
    def commit_claim(self) -> CommitClaim:
        return self.page_source.commit_claim

    def accepts_commit(self, cursor: TranscriptCursor) -> bool:
        return self.page_source.accepts_commit(cursor)

    def covered_sequences(self, sequences: frozenset[int]) -> frozenset[int]:
        return frozenset(sequence for sequence in sequences if self.covers_incoming(sequence))

    def covers_outgoing(self, message: PublishedSentMessage) -> bool:
        return message.reference in self.outgoing_coverage

    @property
    def coverage(self) -> HistoryCoverage:
        return self._source_state.coverage

    def source_resumed(self) -> None:
        super().source_resumed()
        self.coverage.publish(self)

    def publish_committed(self) -> None:
        """Acquire source ownership now; report coverage after its first painted frame."""
        self._source_state = self._source_state.publish()
        self.call_after_refresh(self.publish_coverage)
        self.request_preparation()

    def publish_coverage(self) -> None:
        self.coverage.publish(self)

    @property
    def coverage_events(self) -> Iterator[TranscriptEvent]:
        return (event for page in self.pages for event in page.prepared.page.events)

    @property
    def source_through(self) -> TranscriptCursor:
        return self.page_source.through

    def covered_outgoing(self) -> frozenset[OutgoingMessageReference]:
        return frozenset(reference for page in self.pages
                         for reference in page.prepared.outgoing_coverage
                         ) | self.filter.overlay.outgoing_coverage

    def overlay_covers_incoming(self, sequence: int) -> bool:
        return self.filter.overlay.covers_incoming(sequence)

    def publish_covered(self) -> None:
        self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))

    @property
    def outgoing_coverage(self):
        return self.coverage.outgoing(self)

    def covers_incoming(self, sequence: int) -> bool:
        return self.coverage.covers_incoming(self, sequence)

    def covers_input(self, started: InputStartedUpdate) -> bool:
        """Whether the loaded saved pages hold the input Core started under this identity."""
        return self.coverage.covers_input(self, started)

    def retain_committed(self, through: TranscriptCursor) -> None:
        """Extend access to saved source without moving the displayed page window."""
        if not self.accepts_commit(through):
            raise ValueError("Commit replaces or rewinds the retained source")
        self.extend_source(through)

    async def park_document(self) -> PreparedPageSource:
        """Stop reading and hand the drawn pages to their reader, to be rebuilt on return.

        Satisfies the `CoveredHistory.park_document` abstract. All primitives are
        toolkit-neutral (`retire_source` on `HistoryPager`, `filter.overlay.park_document`
        on `FilterState`, `page_source` on `HistoryPager`, `page.prepared` on `ReaderPage`),
        so both Textual's `CommittedHistory` and Qt's `QtTranscriptHistory` share one
        implementation. Hoisted out of `widgets/transcript_history.py:LineHistory` for
        PR #1945 so Qt is not re-stating the same body.
        """
        await self.retire_source(parked=True)
        source = self.page_source
        projected = await self.filter.overlay.park_document()
        pages = tuple(page.prepared for page in self.pages)
        await source.runtime.run_thread(source.measure_held, pages, projected)
        source.park(pages, projected)
        return source
