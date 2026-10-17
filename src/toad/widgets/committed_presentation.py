"""Source evidence and viewport intent govern retirement of live presentation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.widget import Widget
from agent_comms.transcript_events import TranscriptEvent
from toad.transcript_state import CommitTranscript, LatestViewportRequest
from agent_comms.sent_message import PublishedSentMessage, OutgoingMessageReference
from toad.core.source_events import TranscriptCoverage
from agent_comms.acp_extension import InputStartedUpdate

from toad.block_navigation import ConversationBlock
from toad.widgets.history_anchor import LatestPosition
from toad.widgets.presentation_window import protected_presentations

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation
    from toad.widgets.history_anchor import HistoryWindow
    from toad.transcript_preparation import PreparedTranscriptPage
    from toad.widgets.transcript_fragments import TranscriptFragment

@dataclass(frozen=True)
class CommitEvidence:
    captured: frozenset[Widget]
    sequences: frozenset[int] = frozenset()
    retained_history: Widget | None = None
    native_inputs: frozenset[str] = frozenset()
    outgoing: frozenset[OutgoingMessageReference] = frozenset()

class CommitClaim(ABC):
    def capture(self, settled: bool) -> bool:
        return True

    def accepts_native(self, widget: Widget, captured: frozenset[Widget]) -> bool:
        return True

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset()

    @abstractmethod
    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        pass

class CapturedClaim(CommitClaim):
    """A settled source-owned block captured before the snapshot read."""

    def capture(self, settled: bool) -> bool:
        return settled

    def accepts_native(self, widget: Widget, captured: frozenset[Widget]) -> bool:
        return widget in captured

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return widget in evidence.captured and widget is not evidence.retained_history

@dataclass(frozen=True)
class ToolOutputClaim(CapturedClaim):
    """A compact tool cannot retire before its separate bodies are supplied."""

    outgoing: frozenset[OutgoingMessageReference]

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return super().covered(widget, evidence) and self.outgoing <= evidence.outgoing

class RetainedSourceClaim(CapturedClaim):
    """An original saved source is transferable independently of live output."""

    def capture(self, settled: bool) -> bool:
        return True

    def accepts_native(self, widget: Widget, captured: frozenset[Widget]) -> bool:
        return True

@dataclass(frozen=True)
class SequenceClaim(CommitClaim):
    """A wire notice needs its exact persisted counterpart, not a save signal."""

    sequence: int | None

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset((self.sequence,)) if self.sequence is not None and self.sequence > 0 else frozenset()

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.sequence is not None and self.sequence in evidence.sequences

@dataclass(frozen=True)
class OutgoingMessageClaim(CommitClaim):
    message: PublishedSentMessage

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.message.reference in evidence.outgoing

@dataclass(frozen=True)
class StartedInputClaim(CommitClaim):
    """An original started input retires only against its saved native identity."""

    source: InputStartedUpdate

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.source.native_id in evidence.native_inputs

class CommitParticipant:
    """Nominal widget contract; unrelated/local widgets are retained by default."""

    @property
    def commit_claim(self) -> CommitClaim:
        raise NotImplementedError

class SnapshotPresentation(CommitParticipant):
    @property
    def commit_claim(self) -> CommitClaim:
        return CAPTURED_CLAIM

class CommitBarrier:
    """A local interactive session whose ordering cannot be replaced by a snapshot."""

CAPTURED_CLAIM = CapturedClaim()
RETAINED_SOURCE_CLAIM = RetainedSourceClaim()

class CommittedHistory(ConversationBlock, SnapshotPresentation):
    """A saved source block that precedes the conversation's live tail."""

    conversation_order = 0

    @property
    def commit_claim(self) -> CommitClaim:
        return RETAINED_SOURCE_CLAIM

    def accepts_commit(self, cursor: TranscriptCursor) -> bool:
        return cursor.contains(self.committed_cursor)

    def covered_sequences(self, sequences: frozenset[int]) -> frozenset[int]:
        return frozenset(sequence for sequence in sequences if self.covers_incoming(sequence))

    def covers_outgoing(self, message: PublishedSentMessage) -> bool:
        return message.reference in self.outgoing_coverage

    def source_resumed(self) -> None:
        if self._source_state.reports_coverage:
            self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        # The live blocks this page covers are retired as part of adding
        # the page, without holding the conversation's message pump. A
        # saved viewer outside a conversation has no live blocks.
        if self._source_state.reports_coverage and (conversation := self.conversation) is not None:
            conversation.transcript.covered(TranscriptCoverage(page.events), self).call_when_ready(conversation)

    def publish_committed(self) -> None:
        """Acquire source ownership now; report coverage after its first painted frame."""
        self._source_state = self._source_state.publish()
        self.call_after_refresh(self.publish_coverage)
        self.request_preparation()

    def publish_coverage(self) -> None:
        if self._source_state.reports_coverage:
            self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))

    @property
    def coverage_events(self) -> Iterator[TranscriptEvent]:
        return (event for page in self.pages for event in page.page.events)

    @property
    def outgoing_coverage(self):
        if self._source_state.reports_coverage:
            references = frozenset(reference for page in self.pages
                                   for reference in page.prepared.outgoing_coverage)
            projection = self.filter.overlay
            return references | (projection.outgoing_coverage if projection is not None else frozenset())
        return frozenset()

    def covers_incoming(self, sequence: int) -> bool:
        if not self._source_state.reports_coverage:
            return False
        if self.committed_cursor.covers_incoming(sequence):
            return True
        if sequence in TranscriptCoverage(tuple(self.coverage_events)).sequences:
            return True
        return self.filter.covers_incoming(sequence)

    def covers_input(self, native_id: str | None) -> bool:
        """Whether the loaded saved pages hold the input Core started under this identity."""
        return (self._source_state.reports_coverage
                and native_id in TranscriptCoverage(tuple(self.coverage_events)).native_inputs)

    @property
    def committed_cursor(self) -> TranscriptCursor:
        return self.through

    def retain_committed(self, through: TranscriptCursor) -> None:
        """Extend access to saved source without moving the displayed page window."""
        if not self.accepts_commit(through):
            raise ValueError("Commit replaces or rewinds the retained source")
        self.extend_source(through)

    async def advance_committed(
        self, through: TranscriptCursor, is_current: Callable[[], bool],
        live_blocks: tuple[Widget, ...],
    ) -> bool:
        """Extend a complete followed tail; read a bounded destination across a gap.

        The pages already drawn stay. The saved rows replace `live_blocks`,
        the live copies of the same turn, in the change that draws them.
        """
        async with self.window.history_lock:
            if not self.source_ready or not is_current():
                return False
            if not self.accepts_commit(through):
                raise ValueError("Commit replaces or rewinds the saved source")
            operation = self.reserve_source_work(partial(CommitTranscript, live_blocks=live_blocks))
        return await operation.execute(self, partial(self._advance_committed, through, is_current))

    async def _advance_committed(
        self, through: TranscriptCursor, is_current: Callable[[], bool],
    ) -> bool:
        if not is_current() or not self.state.can_draw:
            return False
        if not self.has_newer:
            return await self.extend(through, is_current)
        self.retain_committed(through)
        request = LatestViewportRequest(LatestPosition.hold(self.window))
        return await self._jump_latest(request, is_current)

def retirement_candidates(widgets: Iterable[Widget], evidence: CommitEvidence) -> list[Widget]:
    return [widget for widget in widgets
            if isinstance(widget, CommitParticipant) and widget.commit_claim.covered(widget, evidence)]

def required_sequences(widgets: Iterable[Widget]) -> frozenset[int]:
    return frozenset(sequence for widget in widgets if isinstance(widget, CommitParticipant)
                     for sequence in widget.commit_claim.required_sequences)

def protected_blocks(view: Conversation, candidates: Iterable[Widget]) -> set[Widget]:
    endpoints = set(view.screen._interaction_widgets())
    if view.cursor_block is not None:
        endpoints.add(view.cursor_block)
    return protected_presentations(candidates, endpoints)

@dataclass(frozen=True)
class PreparedCommit:
    history: CommittedHistory | None
    page: PreparedTranscriptPage | None
    sequences: frozenset[int]

    @property
    def outgoing(self) -> frozenset[OutgoingMessageReference]:
        if self.page is not None:
            return self.page.outgoing_coverage
        return self.history.outgoing_coverage

class CommitPlan(ABC):
    """A viewport-owned policy; the coordinator does not branch on block types."""

    @abstractmethod
    def current(self, window: HistoryWindow) -> bool:
        pass

    def permits(self, view: Conversation, candidates: Iterable[Widget]) -> bool:
        return not protected_blocks(view, candidates)

    def ready(self, history: CommittedHistory | None) -> bool:
        return history is None or history.source_ready

    async def prepare(self, view: Conversation, history: CommittedHistory | None,
                      page: TranscriptPage, captured: frozenset[Widget],
                      is_current: Callable[[], bool]) -> PreparedCommit | None:
        """Grow a history that accepts the page; otherwise the page replaces it."""
        from toad.transcript_preparation import TranscriptPageRenderTask
        from toad.work_preparation import RenderPreparation

        if history is not None and history.accepts_commit(page.after):
            return await self.extend(view, history, page, captured, is_current)
        prepared = await view.app.preparation.submit(RenderPreparation(TranscriptPageRenderTask(page)))
        return PreparedCommit(None, prepared, TranscriptCoverage(page.events).sequences)

    @abstractmethod
    async def extend(self, view: Conversation, history: CommittedHistory, page: TranscriptPage,
                     captured: frozenset[Widget], is_current: Callable[[], bool]) -> PreparedCommit | None:
        """Commit the page's records onto the history that already ends where it starts."""

    def commit(self, prepared: PreparedCommit, cursor: TranscriptCursor) -> None:
        """Apply source metadata only after the final retirement checks."""

    @asynccontextmanager
    async def publication(self, view: Conversation, prepared: PreparedCommit):
        async with view.window.preserve_history(root=view.contents):
            yield

    def finish(self, view: Conversation, cursor: TranscriptCursor) -> None:
        """A retained viewport does not claim that newer records were painted."""

class FollowTailCommit(CommitPlan):
    def __init__(self, window: HistoryWindow) -> None:
        self.revision = window.scroll_revision

    def current(self, window: HistoryWindow) -> bool:
        return window.follows_tail and window.scroll_revision == self.revision

    async def extend(self, view, history, page, captured, is_current):
        # The drawn history grows in place: unchanged pages keep their views,
        # and the captured live blocks leave in the change that draws their saved rows.
        live_blocks = tuple(retirement_candidates(
            captured, CommitEvidence(frozenset(captured), retained_history=history),
        ))
        if not await history.advance_committed(page.after, is_current, live_blocks):
            return None
        return PreparedCommit(history, None, TranscriptCoverage(page.events).sequences
                              | history.covered_sequences(required_sequences(captured)))

    def finish(self, view, cursor):
        view.transcript.painted(cursor)
        view.call_after_refresh(self.restore_reader, view.window)

    def restore_reader(self, window):
        # The publication's captured intent owns its deferred layout effect as
        # well. A later scroll or source return cannot inherit an older anchor.
        if self.current(window):
            window.anchor()

class RetainViewportCommit(CommitPlan):
    def current(self, window: HistoryWindow) -> bool:
        # Extending the source leaves the loaded rows and reader position intact.
        # Retirement checks the current viewport again when applying the change.
        return not window.follows_tail

    def permits(self, view, candidates):
        candidates = tuple(candidates)
        if not super().permits(view, candidates):
            return False
        # Hidden tabs have no exposed viewport. Never request offscreen geometry
        # (which could rebuild the whole scene) to decide retirement.
        if not view.screen.is_current:
            return True
        visible = view.screen._compositor.published_widgets
        viewport = view.window.published_content_region
        if viewport is None:
            return True
        return not any(widget in visible and visible[widget][0].overlaps(viewport)
                       for widget in candidates)

    async def extend(self, view, history, page, captured, is_current):
        required = required_sequences(captured)
        known = TranscriptCoverage(page.events).sequences | history.covered_sequences(required)
        covered = frozenset(sequence for sequence in required
                            if page.after.covers_incoming(sequence))
        return PreparedCommit(history, None, known | covered)

    def commit(self, prepared, cursor):
        if prepared.history is not None:  # A replacement history already owns its source.
            prepared.history.retain_committed(cursor)

def commit_plan(window: HistoryWindow) -> CommitPlan:
    return FollowTailCommit(window) if window.follows_tail else RetainViewportCommit()
