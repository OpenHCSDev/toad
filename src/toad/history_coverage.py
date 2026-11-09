"""What a saved history's source state says its loaded pages cover."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from typing import ClassVar

from agent_comms.acp_extension import InputStartedUpdate
from agent_comms.messaging.sent_message import OutgoingMessageReference
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.transcript.transcript_events import TranscriptCoverage, TranscriptEvent
from agent_comms.transcript.transcripts import TranscriptCursor, TranscriptPage
from textual.abstract_hooks import AbstractHooksMeta


class CoveredHistory[Document](metaclass=AbstractHooksMeta):
    """What coverage reads from a saved history and asks it to do."""

    @property
    @abstractmethod
    def coverage_events(self) -> Iterator[TranscriptEvent]: ...

    @property
    @abstractmethod
    def source_through(self) -> TranscriptCursor: ...

    @abstractmethod
    def covered_outgoing(self) -> frozenset[OutgoingMessageReference]: ...

    @abstractmethod
    def overlay_covers_incoming(self, sequence: int) -> bool: ...

    @abstractmethod
    def publish_covered(self) -> None:
        """Announce the loaded pages' coverage to Core."""

    @abstractmethod
    async def park_document(self) -> Document: ...

    @abstractmethod
    def close(self) -> None: ...


class ReportsCoveredPages(metaclass=AbstractHooksMeta):
    """A history whose own page reads reach the presentation's coverage evidence."""

    @abstractmethod
    def page_covered(self, page: TranscriptPage) -> None: ...


class HistoryCoverage(DeclaredFamily, affix="Coverage"):
    """The base answers for a source that covers nothing: unread, retired or parked."""

    summary: ClassVar[str] = "Saved history not loaded"

    def outgoing(self, history: CoveredHistory) -> frozenset[OutgoingMessageReference]:
        return frozenset()

    def covers_incoming(self, history: CoveredHistory, sequence: int) -> bool:
        return False

    def covers_input(self, history: CoveredHistory, started: InputStartedUpdate) -> bool:
        return False

    def retained_through(self, history: CoveredHistory) -> tuple[TranscriptCursor, ...]:
        return ()

    def publish(self, history: CoveredHistory) -> None:
        """Nothing covered, nothing to announce."""

    def page_added(self, history: ReportsCoveredPages, page: TranscriptPage) -> None:
        """An uncovered source does not report the page it read."""

    async def retire[Document](self, history: CoveredHistory[Document]) -> tuple[Document, ...]:
        """Nothing parks an uncovered source, so nothing outlives the view to close it."""
        history.close()
        return ()


class NoCoverage(HistoryCoverage):
    """A source whose pages are not yet, or no longer, published as coverage."""


class PageCoverage(HistoryCoverage):
    """A published source covers its loaded pages and the filter's overlay."""

    summary = "Saved history available"

    def outgoing(self, history: CoveredHistory) -> frozenset[OutgoingMessageReference]:
        return history.covered_outgoing()

    def covers_incoming(self, history: CoveredHistory, sequence: int) -> bool:
        return (history.source_through.covers_incoming(sequence)
                or sequence in TranscriptCoverage(tuple(history.coverage_events)).sequences
                or history.overlay_covers_incoming(sequence))

    def covers_input(self, history: CoveredHistory, started: InputStartedUpdate) -> bool:
        return started.native_id in TranscriptCoverage(tuple(history.coverage_events)).native_inputs

    def retained_through(self, history: CoveredHistory) -> tuple[TranscriptCursor, ...]:
        return (history.source_through,)

    def publish(self, history: CoveredHistory) -> None:
        history.publish_covered()

    def page_added(self, history: ReportsCoveredPages, page: TranscriptPage) -> None:
        history.page_covered(page)

    async def retire[Document](self, history: CoveredHistory[Document]) -> tuple[Document, ...]:
        """The parked pages go to the presentation, which closes them when the tab closes."""
        return (await history.park_document(),)


NO_COVERAGE = NoCoverage()
PAGE_COVERAGE = PageCoverage()
