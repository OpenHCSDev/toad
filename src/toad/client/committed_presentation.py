"""Source evidence and viewport intent govern retirement of live presentation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Literal, Self

from agent_comms.acp_extension import TranscriptDraftUpdate, TranscriptSnapshotUpdate
from agent_comms.coordination.errors import TranscriptChanged
from agent_comms.execution.transcript_sources import TranscriptCursor
from agent_comms.messaging.sent_message import OutgoingMessageReference
from agent_comms.transcript.transcript_events import TranscriptCoverage
from agent_comms.transcript.transcripts import TranscriptPage
from formbridge.forms.declared_fields import DeclaredViews
from metaclass_registry.mro_dispatch import handles
from textual.await_complete import AwaitComplete

from toad.client.block_claim import block_claim
from toad.client.history_preparation import NEWER_END
from toad.client.history_state import PreparedReplacementViewportRequest, TranscriptState, WorkingTranscript
from toad.client.prepared_pages import PreparedPageSource, SavedHistory
from toad.client.reader_position import LatestPosition
from toad.commit_claims import (
    CommitClaim,
    CommitEvidence,
    LiveResponsePresentation,
)
from toad.core.projection import MroProjection
from toad.transcript_preparation import TranscriptPageRenderTask

if TYPE_CHECKING:

    from toad.client.prepared_pages import PreparedTranscriptPage
    from toad.widgets.conversation import Conversation
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import CommittedHistory, TranscriptHistory


class DraftCoverage(MroProjection[bool]):
    """Whether a live block already draws the in-progress assistant reply."""

    @handles(object)
    def uncovered(self, widget: object) -> bool:
        return False

    @handles(LiveResponsePresentation)
    def covered(self, widget: LiveResponsePresentation) -> bool:
        return True


DRAFT_COVERAGE = DraftCoverage()


def covers_live_draft(widget: object) -> bool:
    return DRAFT_COVERAGE.project_value(widget)


def retirement_candidates(widgets: Iterable[object], evidence: CommitEvidence) -> list[object]:
    return [widget for widget in widgets if block_claim(widget).covered(widget, evidence)]


def required_sequences(widgets: Iterable[object]) -> frozenset[int]:
    return frozenset(sequence for widget in widgets for sequence in block_claim(widget).required_sequences)


@dataclass(frozen=True)
class PreparedCommit(DeclaredViews):
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

    @classmethod
    def catches_up_at_latest(cls, snapshot: object) -> bool:
        """Only an append commit over a multi-page gap jumps straight to the latest window."""
        return False

    async def draw(self, cursor: TranscriptCursor, is_current: Callable[[], bool],
                   live_blocks: tuple[object, ...]) -> bool:
        """A retained viewport changes source access without drawing rows."""
        return True


@dataclass(frozen=True)
class PreparedPageCommit(PreparedCommit, shows=(PreparedPageSource,)):
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
        classes = history.fragment_classes
        files = await view.transcript.page_files(page, classes)
        prepared = await TranscriptPageRenderTask(page, classes, files).prepared(view.app.preparation)
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


class PreparedAppendCommit(PreparedPageCommit, shows=(SavedHistory,)):
    """The saved source extends its original pages, retaining their rendered prefix."""

    @classmethod
    async def read_snapshot[Snapshot](
        cls, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        return await read(position=history.page_source.through.later_page())

    @classmethod
    def catches_up_at_latest(cls, snapshot: object) -> bool:
        return SNAPSHOT_HAS_NEWER.project_value(snapshot)

    async def publish(self, cursor: TranscriptCursor, is_current: Callable[[], bool]) -> bool:
        return await self.history.publish_append(cursor, publication_current=is_current)


class SnapshotHasNewer(MroProjection[bool]):
    """Whether a transcript update leaves unread pages after the returned one."""

    @handles(TranscriptSnapshotUpdate)
    def snapshot(self, update: TranscriptSnapshotUpdate) -> bool:
        return update.page.has_newer

    @handles(TranscriptDraftUpdate)
    def draft(self, update: TranscriptDraftUpdate) -> bool:
        return False


SNAPSHOT_HAS_NEWER = SnapshotHasNewer()


class CommitPlan(ABC):
    """Capture source acquisition and viewport publication together for one read."""

    preparation: type[PreparedCommit]

    def preparation_for_source(self, source: type[PreparedPageCommit]) -> type[PreparedCommit]:
        """A held viewport retains its original paint after a successful read."""
        return PreparedCommit

    def catches_up_at_latest(self, snapshot: object) -> bool:
        """A retained viewport keeps its place; only a following reader jumps past a multi-page gap."""
        return False

    async def read_snapshot[Snapshot](
        self, read: Callable[..., Awaitable[Snapshot]], history: CommittedHistory,
    ) -> Snapshot:
        """The source declares acquisition; its result fixes this read's publication."""
        source = PreparedPageCommit.showing(type(history.page_source).__mro__)
        self.preparation = self.preparation_for_source(source)
        try:
            snapshot = await source.read_snapshot(read, history)
        except TranscriptChanged:
            # A full retry is a replacement, even when the file path is reused
            # and its new cursor contains the old byte offset.
            self.preparation = PreparedPageCommit
            return await PreparedPageCommit.read_snapshot(read, history)
        if self.catches_up_at_latest(snapshot):
            # More than one page accumulated while this tab sat behind: jump straight to
            # the latest window instead of rendering and committing every intermediate page
            # serially; backwards lazy-loading pulls older pages on demand.
            self.preparation = PreparedPageCommit
            return await PreparedPageCommit.read_snapshot(read, history)
        return snapshot

    @abstractmethod
    def current(self, window: HistoryWindow) -> bool:
        pass

    def permits(self, view: Conversation, candidates: Iterable[object]) -> bool:
        return not view.protected_blocks(candidates)

    def ready(self, history: CommittedHistory) -> bool:
        return history.source_ready

    async def prepare(self, view: Conversation, history: TranscriptHistory,
                      page: TranscriptPage, captured: frozenset[object]) -> PreparedCommit:
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

    def catches_up_at_latest(self, snapshot: object) -> bool:
        return self.preparation.catches_up_at_latest(snapshot)

    def finish(self, view, cursor) -> None:
        view.transcript.binding.painted(view.transcript, cursor)
        view.after_refresh(partial(self.restore_reader, view.window))

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
        return super().permits(view, candidates) and not view.blocks_in_viewport(candidates)

    def commit(self, prepared, cursor) -> None:
        prepared.history.retain_committed(cursor)


def commit_plan(window: HistoryWindow) -> CommitPlan:
    return FollowTailCommit(window) if window.follows_tail else RetainViewportCommit()


class CommitTranscript(WorkingTranscript):
    """A commit's advance: its saved rows replace the live blocks captured with its page.

    The live blocks leave in the same tree change that draws the last saved
    row, so no frame shows both copies of the turn, or neither.
    """

    def __init__(self, source: TranscriptState, owner, live_blocks: tuple[object, ...],
                 claims: tuple[CommitClaim, ...]):
        super().__init__(source, owner)
        self.live_blocks = live_blocks
        self.claims = claims
        self.retirement = AwaitComplete.nothing()

    async def execute[Result](self, owner, work: Callable[[], Awaitable[Result]]) -> Result | Literal[False]:
        try:
            return await super().execute(owner, work)
        finally:
            await self.retirement

    def arriving(self, prepared: PreparedTranscriptPage, followed_end: bool):
        # Rows its live blocks already showed have not arrived again; every other row has.
        # The live blocks are the commit participants `retirement_candidates` chose.
        return tuple(
            fragment
            for fragment in super().arriving(prepared, followed_end)
            if not any(fragment.shown_live_by(claim) for claim in self.claims)
        )

    def rows_published(self, owner) -> None:
        super().rows_published(owner)
        if self.live_blocks and not NEWER_END.visible_more(owner):
            blocks, self.live_blocks = self.live_blocks, ()
            self.retirement = owner.view.retire_blocks(blocks)
