"""Source evidence and viewport intent govern retirement of live presentation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Self

from agent_comms.acp_extension import InputStartedUpdate
from agent_comms.coordination_errors import TranscriptChanged
from agent_comms.sent_message import OutgoingMessageReference, PublishedSentMessage
from agent_comms.transcript_events import TranscriptCoverage
from agent_comms.transcripts import (
    NativeCommittedPrefix,
    TranscriptCursor,
    TranscriptPage,
    TranscriptReadIdentity,
)
from textual.widget import Widget

from toad.transcript_state import CommitTranscript, PreparedReplacementViewportRequest
from toad.widgets.history_anchor import LatestPosition
from toad.widgets.presentation_window import protected_presentations

if TYPE_CHECKING:
    from toad.transcript_preparation import PreparedTranscriptPage
    from toad.widgets.conversation import Conversation
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_fragments import (
        BusMessageFragment,
        SentMessageFragment,
        TranscriptFragment,
    )
    from toad.widgets.transcript_history import CommittedHistory, TranscriptHistory

@dataclass(frozen=True)
class CommitEvidence:
    captured: frozenset[Widget]
    sequences: frozenset[int] = frozenset()
    retained_history: Widget | None = None
    native_inputs: frozenset[str] = frozenset()
    outgoing: frozenset[OutgoingMessageReference] = frozenset()

    def covers_native(self, source: NativeCommittedPrefix) -> bool:
        return False


@dataclass(frozen=True, kw_only=True)
class NativeCommitEvidence(CommitEvidence):
    identity: TranscriptReadIdentity

    def covers_native(self, source: NativeCommittedPrefix) -> bool:
        return source.contains_native_prefix(self.identity)


class CommitSource:
    """Uncommitted output needs settlement; a native append supplies exact coverage."""

    def capture(self, settled: bool) -> bool:
        return settled

    def accepts(self, identity: TranscriptReadIdentity) -> bool:
        return True

    def covered(self, evidence: CommitEvidence) -> bool:
        return True

    def prefixes(self, identity: TranscriptReadIdentity, cursor: TranscriptCursor) -> tuple[TranscriptCursor, ...]:
        return ()


@dataclass(frozen=True)
class NativeCommitSource(CommitSource):
    original: NativeCommittedPrefix

    def capture(self, settled: bool) -> bool:
        return True

    def accepts(self, identity: TranscriptReadIdentity) -> bool:
        return self.original.contains_native_prefix(identity)

    def covered(self, evidence: CommitEvidence) -> bool:
        return evidence.covers_native(self.original)

    def prefixes(self, identity: TranscriptReadIdentity, cursor: TranscriptCursor) -> tuple[TranscriptCursor, ...]:
        return (self.original.page_bound.with_frontier(cursor.wire),) if self.accepts(identity) else ()

class CommitClaim(ABC):
    def capture(self, settled: bool) -> bool:
        return True

    def accepts_native(self, widget: Widget, captured: frozenset[Widget],
                       identity: TranscriptReadIdentity) -> bool:
        return True

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset()

    @abstractmethod
    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        pass

    # Whether the live block already showed a saved row its commit retires it for;
    # a row no live block showed arrives (`CommitTranscript.arriving`).
    def repeats_native(self, fragment: TranscriptFragment) -> bool:
        return False

    def repeats_received(self, fragment: BusMessageFragment) -> bool:
        return False

    def repeats_sent(self, fragment: SentMessageFragment) -> bool:
        return False

@dataclass(kw_only=True)
class CapturedClaim(CommitClaim):
    """A captured block, sealed by its original append or a settled turn."""

    source: CommitSource = field(default_factory=CommitSource)

    def seal(self, source: NativeCommittedPrefix) -> None:
        self.source = NativeCommitSource(source)

    def capture(self, settled: bool) -> bool:
        return self.source.capture(settled)

    def accepts_native(self, widget: Widget, captured: frozenset[Widget],
                       identity: TranscriptReadIdentity) -> bool:
        return widget in captured and self.source.accepts(identity)

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return (widget in evidence.captured and widget is not evidence.retained_history
                and self.source.covered(evidence))

    def repeats_native(self, fragment: TranscriptFragment) -> bool:
        # The snapshot captured the native output its saved records hold.
        return True

@dataclass
class ToolOutputClaim(CapturedClaim):
    """A compact tool cannot retire before its separate bodies are supplied."""

    outgoing: frozenset[OutgoingMessageReference]

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return super().covered(widget, evidence) and self.outgoing <= evidence.outgoing

    def repeats_sent(self, fragment: SentMessageFragment) -> bool:
        return fragment.publication.reference in self.outgoing

class RetainedSourceClaim(CapturedClaim):
    """An original saved source is transferable independently of live output."""

    def capture(self, settled: bool) -> bool:
        return True

    def accepts_native(self, widget: Widget, captured: frozenset[Widget],
                       identity: TranscriptReadIdentity) -> bool:
        return True

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return widget is not evidence.retained_history

@dataclass(frozen=True)
class SequenceClaim(CommitClaim):
    """A wire notice needs its exact persisted counterpart, not a save signal."""

    sequence: int | None

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset((self.sequence,)) if self.sequence is not None and self.sequence > 0 else frozenset()

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.sequence is not None and self.sequence in evidence.sequences

    def repeats_received(self, fragment: BusMessageFragment) -> bool:
        return self.sequence in TranscriptCoverage(fragment.events).sequences

@dataclass(frozen=True)
class OutgoingMessageClaim(CommitClaim):
    message: PublishedSentMessage

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.message.reference in evidence.outgoing

    def repeats_sent(self, fragment: SentMessageFragment) -> bool:
        return fragment.publication.reference == self.message.reference

@dataclass(frozen=True)
class StartedInputClaim(CommitClaim):
    """An original started input retires only against its saved native identity."""

    source: InputStartedUpdate

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.source.native_id in evidence.native_inputs

    def repeats_native(self, fragment: TranscriptFragment) -> bool:
        return self.source.native_id in TranscriptCoverage(fragment.events).native_inputs

class CommitParticipant:
    """Nominal widget contract; unrelated/local widgets are retained by default."""

    @property
    def commit_claim(self) -> CommitClaim:
        raise NotImplementedError

CAPTURED_CLAIM = CapturedClaim()
RETAINED_SOURCE_CLAIM = RetainedSourceClaim()


class SnapshotPresentation(CommitParticipant):
    source_claim: CapturedClaim = CAPTURED_CLAIM

    @property
    def committed_source(self) -> CommitSource:
        return self.source_claim.source

    @property
    def commit_claim(self) -> CommitClaim:
        return self.source_claim

class CommitBarrier:
    """A local interactive session whose ordering cannot be replaced by a snapshot."""

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
    history: CommittedHistory
    sequences: frozenset[int]

    @property
    def outgoing(self) -> frozenset[OutgoingMessageReference]:
        return self.history.outgoing_coverage

    async def draw(self, cursor: TranscriptCursor, is_current: Callable[[], bool],
                   live_blocks: tuple[Widget, ...]) -> bool:
        """A retained viewport changes source access without drawing rows."""
        return True


@dataclass(frozen=True)
class PreparedPageCommit(PreparedCommit):
    """Publish the acquired destination page through the live-block handoff."""

    history: TranscriptHistory
    page: PreparedTranscriptPage

    @classmethod
    async def capture(cls, view: Conversation, history: TranscriptHistory, page: TranscriptPage, sequences: frozenset[int]) -> Self:
        from toad.transcript_preparation import TranscriptPageRenderTask
        from toad.work_preparation import RenderPreparation

        prepared = await view.app.preparation.submit(RenderPreparation(TranscriptPageRenderTask(page)))
        return cls(history, sequences, prepared)

    @property
    def outgoing(self) -> frozenset[OutgoingMessageReference]:
        return self.history.outgoing_coverage | self.page.outgoing_coverage

    async def draw(self, cursor, is_current: Callable[[], bool], live_blocks) -> bool:
        history = self.history
        async with history.window.history_lock:
            if not history.source_ready or not is_current():
                return False
            operation = history.reserve_source_work(partial(CommitTranscript, live_blocks=live_blocks))
        return await operation.execute(history, partial(
            history.show_newest,
            PreparedReplacementViewportRequest(LatestPosition.hold(history.window), self.page),
            publication_current=is_current,
        ))


class CommitPlan(ABC):
    """The captured viewport intent owns source acquisition and publication."""

    @abstractmethod
    async def read_snapshot[Snapshot](
        self, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        """Acquire the saved destination this plan will publish."""

    @abstractmethod
    def current(self, window: HistoryWindow) -> bool:
        pass

    def permits(self, view: Conversation, candidates: Iterable[Widget]) -> bool:
        return not protected_blocks(view, candidates)

    def ready(self, history: CommittedHistory) -> bool:
        return history.source_ready

    async def prepare(self, view: Conversation, history: TranscriptHistory,
                      page: TranscriptPage, captured: frozenset[Widget]) -> PreparedCommit:
        """Share exact wire coverage; each destination owns its render action."""
        sequences = TranscriptCoverage(page.events).sequences
        if history.accepts_commit(page.after):
            required = required_sequences(captured)
            sequences |= history.covered_sequences(required) | frozenset(
                sequence for sequence in required if page.after.covers_incoming(sequence)
            )
            return await self.extend(view, history, page, sequences)
        return await PreparedPageCommit.capture(view, history, page, sequences)

    @abstractmethod
    async def extend(self, view: Conversation, history: TranscriptHistory, page: TranscriptPage,
                     sequences: frozenset[int]) -> PreparedCommit:
        """Prepare publication within the history's existing source."""

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

    async def read_snapshot[Snapshot](
        self, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        # No after cursor: Core reads newest-first at its captured saved cut.
        return await read()

    def current(self, window: HistoryWindow) -> bool:
        return window.follows_tail and window.scroll_revision == self.revision

    async def extend(self, view: Conversation, history: TranscriptHistory, page: TranscriptPage,
                     sequences: frozenset[int]) -> PreparedPageCommit:
        return await PreparedPageCommit.capture(view, history, page, sequences)

    def finish(self, view, cursor) -> None:
        view.transcript.binding.painted(view.transcript, cursor)
        view.call_after_refresh(self.restore_reader, view.window)

    def restore_reader(self, window) -> None:
        # The publication's captured intent owns its deferred layout effect as
        # well. A later scroll or source return cannot inherit an older anchor.
        if self.current(window):
            window.anchor()

class RetainViewportCommit(CommitPlan):
    async def read_snapshot[Snapshot](
        self, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        try:
            return await read(after=history.page_source.through)
        except TranscriptChanged:
            # A replaced source cannot extend the old reader's source range.
            return await read()

    def current(self, window: HistoryWindow) -> bool:
        # Extending the source leaves the loaded rows and reader position intact.
        # Retirement checks the current viewport again when applying the change.
        return not window.follows_tail

    def permits(self, view, candidates) -> bool:
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

    async def extend(self, view: Conversation, history: TranscriptHistory, page: TranscriptPage,
                     sequences: frozenset[int]) -> PreparedCommit:
        return PreparedCommit(history, sequences)

    def commit(self, prepared, cursor) -> None:
        prepared.history.retain_committed(cursor)

def commit_plan(window: HistoryWindow) -> CommitPlan:
    return FollowTailCommit(window) if window.follows_tail else RetainViewportCommit()
