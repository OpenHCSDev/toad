"""What a saved history's source state says its loaded pages cover."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agent_comms.acp_extension import InputStartedUpdate
    from agent_comms.sent_message import OutgoingMessageReference
    from agent_comms.transcript_events import TranscriptEvent
    from agent_comms.transcripts import TranscriptCursor, TranscriptPage

    from toad.core.source_events import TranscriptCoverage
    from toad.transcript_preparation import PreparedPageSource
    from toad.widgets.transcript_history import CommittedHistory, TranscriptHistory


class HistoryCoverage(DeclaredFamily, affix="Coverage"):
    """The base answers for a source that covers nothing: unread, retired or parked."""

    summary: ClassVar[str] = "Saved history not loaded"

    def events(self, history: CommittedHistory) -> Iterator[TranscriptEvent]:
        return iter(())

    def outgoing(self, history: CommittedHistory) -> frozenset[OutgoingMessageReference]:
        return frozenset()

    def covers_incoming(self, history: CommittedHistory, sequence: int) -> bool:
        return False

    def covers_input(self, history: CommittedHistory, started: InputStartedUpdate) -> bool:
        return False

    def retained_through(self, history: CommittedHistory) -> tuple[TranscriptCursor, ...]:
        return ()

    def publish(self, history: CommittedHistory) -> None:
        """Nothing covered, nothing to announce."""

    def page_added(self, history: TranscriptHistory, page: TranscriptPage) -> None:
        """An uncovered source does not report the page it read."""

    async def retire(self, history: CommittedHistory) -> tuple[PreparedPageSource, ...]:
        """Nothing parks an uncovered source, so nothing outlives the view to close it."""
        history.close()
        return ()


class NoCoverage(HistoryCoverage):
    """A source whose pages are not yet, or no longer, published as coverage."""


def _coverage(events) -> TranscriptCoverage:
    # Core's event module imports the transcript states that hold these members.
    from toad.core.source_events import TranscriptCoverage

    return TranscriptCoverage(tuple(events))


class PageCoverage(HistoryCoverage):
    """A published source covers its loaded pages and the filter's overlay."""

    summary = "Saved history available"

    def events(self, history: CommittedHistory) -> Iterator[TranscriptEvent]:
        return history.coverage_events

    def outgoing(self, history: CommittedHistory) -> frozenset[OutgoingMessageReference]:
        references = frozenset(reference for page in history.pages
                               for reference in page.prepared.outgoing_coverage)
        return references | history.filter.overlay.outgoing_coverage

    def covers_incoming(self, history: CommittedHistory, sequence: int) -> bool:
        return (history.page_source.through.covers_incoming(sequence)
                or sequence in _coverage(self.events(history)).sequences
                or history.filter.overlay.covers_incoming(sequence))

    def covers_input(self, history: CommittedHistory, started: InputStartedUpdate) -> bool:
        return started.native_id in _coverage(self.events(history)).native_inputs

    def retained_through(self, history: CommittedHistory) -> tuple[TranscriptCursor, ...]:
        return (history.page_source.through,)

    def publish(self, history: CommittedHistory) -> None:
        history.publish_core(_coverage(self.events(history)))

    def page_added(self, history: TranscriptHistory, page: TranscriptPage) -> None:
        view = history.view
        view.transcript.binding.covered(
            view.transcript, _coverage(page.events), history).call_when_ready(view)

    async def retire(self, history: CommittedHistory) -> tuple[PreparedPageSource, ...]:
        """The parked pages go to the presentation, which closes them when the tab closes."""
        return (await history.park_document(),)


NO_COVERAGE = NoCoverage()
PAGE_COVERAGE = PageCoverage()
