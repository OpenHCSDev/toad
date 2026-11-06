"""Source evidence and viewport intent govern retirement of live presentation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Self

from agent_comms.coordination.errors import TranscriptChanged
from agent_comms.sent_message import OutgoingMessageReference
from agent_comms.transcript_events import TranscriptCoverage
from agent_comms.transcripts import (
    TranscriptCursor,
    TranscriptPage,
)
from metaclass_registry.mro_dispatch import handles
from textual.widget import Widget

from toad.commit_claims import (
    CAPTURED_CLAIM,
    CapturedClaim,
    CommitBarrierClaim,
    CommitClaim,
    CommitEvidence,
    CommitParticipant,
    CommitSource,
    RetainedBlockClaim,
)
from toad.core.projection import MroProjection
from toad.transcript_state import CommitTranscript, PreparedReplacementViewportRequest
from toad.widgets.history_anchor import LatestPosition
from toad.widgets.presentation_window import protected_presentations
from toad.widgets.history_anchor import HistoryWindow

if TYPE_CHECKING:
    from toad.transcript_preparation import PreparedTranscriptPage
    from toad.widgets.conversation import Conversation
    from toad.widgets.transcript_history import CommittedHistory, TranscriptHistory



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


class BlockClaims(MroProjection[CommitClaim]):
    """Every block a conversation's contents hold has one commit claim; this is where it is read."""

    # object, not Widget: a history's MRO reaches Widget before its CommitParticipant base.
    @handles(object)
    def retained(self, widget: Widget) -> CommitClaim:
        return RetainedBlockClaim()

    @handles(CommitParticipant)
    def participant(self, widget: CommitParticipant) -> CommitClaim:
        return widget.commit_claim

    @handles(CommitBarrier)
    def barrier(self, widget: CommitBarrier) -> CommitClaim:
        return CommitBarrierClaim()


BLOCK_CLAIMS = BlockClaims()


def block_claim(widget: Widget) -> CommitClaim:
    return BLOCK_CLAIMS.project_value(widget)


def retirement_candidates(widgets: Iterable[Widget], evidence: CommitEvidence) -> list[Widget]:
    return [widget for widget in widgets if block_claim(widget).covered(widget, evidence)]

def required_sequences(widgets: Iterable[Widget]) -> frozenset[int]:
    return frozenset(sequence for widget in widgets for sequence in block_claim(widget).required_sequences)

def protected_blocks(view: Conversation, candidates: Iterable[Widget]) -> set[Widget]:
    return protected_presentations(candidates, (*view.screen._interaction_widgets(), *view.cursor_block.endpoints))

@dataclass(frozen=True)
class PreparedCommit:
    history: CommittedHistory
    sequences: frozenset[int]

    @classmethod
    async def capture(cls, view: Conversation, history: TranscriptHistory, page: TranscriptPage,
                      sequences: frozenset[int]) -> Self:
        """A retained reader accepts coverage without preparing replacement paint."""
        return cls(history, sequences)

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
    async def read_snapshot[Snapshot](
        cls, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        """Replacement needs the complete destination, even for a closed prefix."""
        return await read()

    @classmethod
    async def capture(cls, view: Conversation, history: TranscriptHistory, page: TranscriptPage, sequences: frozenset[int]) -> Self:
        from toad.transcript_preparation import TranscriptPageRenderTask

        prepared = await TranscriptPageRenderTask(page).prepared(view.app.preparation)
        return cls(history, sequences, prepared)

    @property
    def outgoing(self) -> frozenset[OutgoingMessageReference]:
        return self.history.outgoing_coverage | self.page.outgoing_coverage

    async def draw(self, cursor, is_current: Callable[[], bool], live_blocks) -> bool:
        history = self.history
        async with history.window.history_lock:
            if not history.source_ready or not is_current():
                return False
            operation = history.reserve_source_work(partial(CommitTranscript, live_blocks=live_blocks,
                                                                   claims=tuple(map(block_claim, live_blocks))))
        return await operation.execute(history, partial(self.publish, cursor, is_current))

    async def publish(self, cursor: TranscriptCursor, is_current: Callable[[], bool]) -> bool:
        history = self.history
        return await history.show_newest(
            PreparedReplacementViewportRequest(LatestPosition.hold(history.window), self.page),
            publication_current=is_current,
        )


class PreparedAppendCommit(PreparedPageCommit):
    """The saved source extends its original pages, retaining their rendered prefix."""

    @classmethod
    async def read_snapshot[Snapshot](
        cls, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        return await read(position=history.page_source.through.later_page())

    async def publish(self, cursor: TranscriptCursor, is_current: Callable[[], bool]) -> bool:
        return await self.history.publish_append(cursor, publication_current=is_current)


class CommitPlan(ABC):
    """Capture source acquisition and viewport publication together for one read."""

    preparation: type[PreparedCommit]

    def preparation_for_source(self, source: type[PreparedPageCommit]) -> type[PreparedCommit]:
        """A held viewport retains its original paint after a successful read."""
        return PreparedCommit

    async def read_snapshot[Snapshot](
        self, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        """The source declares acquisition; its result fixes this read's publication."""
        source = history.page_source.commit_preparation
        self.preparation = self.preparation_for_source(source)
        try:
            return await source.read_snapshot(read, history)
        except TranscriptChanged:
            # A full retry is a replacement, even when the file path is reused
            # and its new cursor contains the old byte offset.
            self.preparation = PreparedPageCommit
            return await PreparedPageCommit.read_snapshot(read, history)

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
            return await self.preparation.capture(view, history, page, sequences)
        return await PreparedPageCommit.capture(view, history, page, sequences)

    def commit(self, prepared: PreparedCommit, cursor: TranscriptCursor) -> None:
        """Apply source metadata only after the final retirement checks."""

    @asynccontextmanager
    async def publication(self, view: Conversation, prepared: PreparedCommit):
        async with view.window.preserve_history():
            yield

    def finish(self, view: Conversation, cursor: TranscriptCursor) -> None:
        """A retained viewport does not claim that newer records were painted."""

class FollowTailCommit(CommitPlan):
    def __init__(self, window: HistoryWindow) -> None:
        self.revision = window.scroll_revision

    def current(self, window: HistoryWindow) -> bool:
        return window.follows_tail and window.scroll_revision == self.revision

    def preparation_for_source(self, source: type[PreparedPageCommit]) -> type[PreparedPageCommit]:
        """A following viewport publishes through the same member that acquired it."""
        return source

    def finish(self, view, cursor) -> None:
        view.transcript.binding.painted(view.transcript, cursor)
        view.call_after_refresh(self.restore_reader, view.window)

    def restore_reader(self, window) -> None:
        # The publication's captured intent owns its deferred layout effect as
        # well. A later scroll or source return cannot inherit an older anchor.
        if self.current(window):
            window.anchor()

class RetainViewportCommit(CommitPlan):
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
        viewport = view.window.published_viewport
        return not any(widget in visible and viewport.overlaps(visible[widget][0])
                       for widget in candidates)

    def commit(self, prepared, cursor) -> None:
        prepared.history.retain_committed(cursor)

def commit_plan(window: HistoryWindow) -> CommitPlan:
    return FollowTailCommit(window) if window.follows_tail else RetainViewportCommit()
