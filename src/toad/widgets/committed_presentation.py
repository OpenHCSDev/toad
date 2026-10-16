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
from agent_comms.transcript_events import TranscriptEvent, UserTranscript
from toad.transcript_state import LatestViewportRequest
from agent_comms.sent_message import PublishedSentMessage, OutgoingMessageReference
from toad.core.source_events import TranscriptCoverage
from agent_comms.acp_extension import InputStartedUpdate

from toad.block_navigation import ConversationBlock
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

    def admits_native(self, widget: Widget, captured: frozenset[Widget]) -> bool:
        return True

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset()

    def represents_input(self, input_id: str) -> bool:
        return False

    @abstractmethod
    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        pass

class CapturedClaim(CommitClaim):
    """A settled source-owned block captured before the snapshot read."""

    def capture(self, settled: bool) -> bool:
        return settled

    def admits_native(self, widget: Widget, captured: frozenset[Widget]) -> bool:
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

    def admits_native(self, widget: Widget, captured: frozenset[Widget]) -> bool:
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

class NativeInputClaim(CommitClaim):
    """An original started input retires only against its saved native identity."""

    @property
    @abstractmethod
    def native_id(self) -> str | None: ...

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.native_id in evidence.native_inputs

@dataclass(frozen=True)
class StartedInputClaim(NativeInputClaim):
    """The original native start receipt owns request and journal identity."""

    source: InputStartedUpdate

    @property
    def native_id(self):
        return self.source.native_id

    def represents_input(self, input_id: str) -> bool:
        return self.source.input_id == input_id

@dataclass(frozen=True)
class TranscriptInputClaim(NativeInputClaim):
    source: UserTranscript

    @property
    def native_id(self):
        return self.source.native_id

class CommitParticipant:
    """Nominal widget contract; unrelated/local widgets are retained by default."""

    @property
    def commit_claim(self) -> CommitClaim:
        raise NotImplementedError

class SnapshotPresentation(CommitParticipant):
    @property
    def commit_claim(self) -> CommitClaim:
        return CAPTURED_CLAIM

class CheckpointBarrier:
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
        if self._source_state.reports_coverage:
            from toad.widgets.conversation import Conversation
            # The live blocks this page covers are retired as part of adding
            # the page, without holding the conversation's message pump. A
            # saved viewer outside a conversation has no live blocks.
            for ancestor in self.ancestors:
                if isinstance(ancestor, Conversation):
                    ancestor.transcript.covered(TranscriptCoverage(page.events), self).call_when_ready(ancestor)
                    break

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
            projection = self.filter.state.overlay
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
    ) -> bool:
        """Show the new tail as one prepared destination, not a walk through the gap."""
        async with self.window.history_lock:
            if not self.checkpoint_available or not is_current():
                return False
            # Reject scans started with the old bound without discarding their
            # already accepted filtered overlay or its backward cursor.
            self.retain_committed(through)
            operation = self.reserve_source_work()
        return await operation.execute(self, partial(self._advance_committed, is_current))

    async def _advance_committed(self, is_current: Callable[[], bool]) -> bool:
        if not is_current() or not self.state.can_draw:
            return False
        from toad.widgets.history_anchor import LatestPosition

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

class CheckpointPlan(ABC):
    """A viewport-owned policy; the coordinator does not branch on block types."""

    @abstractmethod
    def current(self, window: HistoryWindow) -> bool:
        pass

    def permits(self, view: Conversation, candidates: Iterable[Widget]) -> bool:
        return not protected_blocks(view, candidates)

    def ready(self, history: CommittedHistory | None) -> bool:
        return history is None or history.checkpoint_available

    @abstractmethod
    async def prepare(self, view: Conversation, history: CommittedHistory | None,
                      page: TranscriptPage, captured: frozenset[Widget],
                      is_current: Callable[[], bool]) -> PreparedCommit | None:
        pass

    def commit(self, prepared: PreparedCommit, cursor: TranscriptCursor) -> None:
        """Apply source metadata only after the final retirement checks."""

    @asynccontextmanager
    async def publication(self, view: Conversation, prepared: PreparedCommit):
        async with view.window.preserve_history(root=view.contents):
            yield

    def finish(self, view: Conversation, cursor: TranscriptCursor) -> None:
        """A retained viewport does not claim that newer records were painted."""

class FollowTailCheckpoint(CheckpointPlan):
    def __init__(self, window: HistoryWindow) -> None:
        self.revision = window.scroll_revision

    def current(self, window: HistoryWindow) -> bool:
        return window.follows_tail and window.scroll_revision == self.revision

    async def prepare(self, view, history, page, captured, is_current):
        from toad.transcript_preparation import TranscriptPageRenderTask
        from toad.work_preparation import RenderPreparation

        # An in-place advance admits bounded pages before its final paint.
        # Anonymous captured output needs the complete source transaction,
        # not an eager mount followed by retirement after that paint.
        transfers = retirement_candidates(
            captured, CommitEvidence(frozenset(captured), retained_history=history),
        )
        if history is not None and history.accepts_commit(page.after) and not transfers:
            if not await history.advance_committed(page.after, is_current):
                return None
            return PreparedCommit(history, None, TranscriptCoverage(page.events).sequences
                                  | history.covered_sequences(required_sequences(captured)))
        prepared = await view.app.preparation.submit(
            RenderPreparation(TranscriptPageRenderTask(page))
        )
        return PreparedCommit(None, prepared, TranscriptCoverage(page.events).sequences)

    def finish(self, view, cursor):
        view.transcript.painted(cursor)
        view.call_after_refresh(self.restore_reader, view.window)

    def restore_reader(self, window):
        # The publication's captured intent owns its deferred layout effect as
        # well. A later scroll or source return cannot inherit an older anchor.
        if self.current(window):
            window.anchor()

class RetainViewportCheckpoint(CheckpointPlan):
    def current(self, window: HistoryWindow) -> bool:
        # Extending the source leaves the loaded rows and reader position intact.
        # Retirement checks the current viewport again when applying the change.
        return not window.follows_tail

    def ready(self, history: CommittedHistory | None) -> bool:
        return history is not None and history.checkpoint_available

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

    async def prepare(self, view, history, page, captured, is_current):

        if (history is None or not history.accepts_commit(page.after)
                or not history.checkpoint_available):
            return None
        required = required_sequences(captured)
        known = TranscriptCoverage(page.events).sequences | history.covered_sequences(required)
        covered = frozenset(sequence for sequence in required
                            if page.after.covers_incoming(sequence))
        return PreparedCommit(history, None, known | covered)

    def commit(self, prepared, cursor):
        assert prepared.history is not None
        prepared.history.retain_committed(cursor)

def checkpoint_plan(window: HistoryWindow) -> CheckpointPlan:
    return FollowTailCheckpoint(window) if window.follows_tail else RetainViewportCheckpoint()
