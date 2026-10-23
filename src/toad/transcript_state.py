"""Transcript publication states and the single Textual lifecycle boundary."""

from abc import ABC, abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
from time import monotonic
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from agent_comms.declared_family import DeclaredFamily
from agent_comms.lifecycle import LifecycleState
from textual.widget import Widget

from toad.resource_release import ResourceRelease
from toad.widgets.presentation_window import NEWER_END, OLDER_END, PageRequest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent_comms.transcripts import TranscriptCursor, TranscriptPage
    from textual.worker import Worker

    from toad.core.events import ThreadRowsChanged
    from toad.transcript_preparation import PreparedPageSource, PreparedTranscriptPage
    from toad.transcript_source_preparation import (
        HistorySourceSnapshot,
        TranscriptSourcePreparation,
    )
    from toad.widgets.committed_presentation import CommitParticipant
    from toad.widgets.history_anchor import HistoryWindow, LatestPosition
    from toad.widgets.transcript_history import (
        ConversationHistory,
        LineHistory,
        ProjectedTranscriptHistory,
    )
    from toad.wire_history import WireCut


class TranscriptState(DeclaredFamily, LifecycleState, affix="Transcript"):
    can_draw: ClassVar[bool] = False
    reports_coverage: ClassVar[bool] = False
    accepts_source_work: ClassVar[bool] = False

    def source_ready(self, owner: TranscriptSourcePreparation) -> bool:
        """The source accepts work and the filter is not scanning."""
        return self.accepts_source_work and owner.filter.idle

    def blocks_visible_read(self, owner: TranscriptSourcePreparation) -> bool:
        """An unpublished source must settle before its cursor is read."""
        return True

    async def execute[Result](
        self, owner: TranscriptSourcePreparation, work: Callable[[], Awaitable[Result]]
    ) -> Result | Literal[False]:
        raise RuntimeError("No transcript source operation is running")

    def reserve(
        self, owner: TranscriptSourcePreparation, operation: type[WorkingTranscript] | None = None
    ) -> WorkingTranscript:
        raise RuntimeError("The transcript source cannot start another operation")

    def request_latest(self, owner: TranscriptSourcePreparation, request: LatestViewportRequest) -> None:
        """An inactive source starts no destination request."""

    def check_edges(self, owner: TranscriptSourcePreparation) -> None:
        """A source that takes no work draws nothing beyond its edges."""

    def delivered(self, owner: TranscriptSourcePreparation) -> None:
        """Only a running source operation measures time to publication."""

    def arriving(self, prepared: PreparedTranscriptPage, followed_end: bool):
        """The staged range begins at the edge this append advances."""
        return prepared.fragments[prepared.start : prepared.stop] if followed_end else ()

    def mounted(self, owner: LineHistory) -> None:
        """An already-read source needs no initial destination request."""

    def rows_published(self, owner: TranscriptSourcePreparation) -> None:
        """Only a commit's advance has live blocks that its saved rows replace."""

    def retirement_source(self) -> TranscriptState:
        return self

    def retire_preparation(self, owner: TranscriptSourcePreparation) -> None:
        """Final source retirement releases its bounded prepared-page scope."""
        owner.close()

    def resume(self) -> TranscriptState:
        raise RuntimeError("Only a parked transcript can resume publication")

    def resume_if_parked(self, owner: TranscriptSourcePreparation) -> None:
        """Showing a resource does not start work on an inactive source."""

    def validate_snapshot(self, owner: TranscriptSourcePreparation, page: TranscriptPage) -> None:
        """A captured source page may validate its existing parked resource."""

    def observed(self, widget: Widget) -> TranscriptState:
        # Textual sets these before dispatching Prune/Unmount, including when
        # an ancestor is removed. Decode at this framework boundary so an
        # async page cannot publish during that interval. They are framework
        # facts, never independent fields maintained by TranscriptHistory.
        if widget.is_leaving:
            return ClosingTranscript(self)
        if not widget.is_attached:
            return DetachedTranscript(self)
        return self

    def for_projection(self, projection: ProjectedTranscriptHistory, owner: LineHistory | None) -> TranscriptState:
        """A view may publish only while its source still owns that projection."""
        if owner is None or not owner.state.can_draw or not owner.filter.owns_projection(projection):
            return RetiredProjectionTranscript(self)
        return self

    @abstractmethod
    def publish(self) -> TranscriptState: ...


class ProvisionalTranscript(TranscriptState):
    @classmethod
    def successors(cls):
        return (LiveTranscript, DetachedTranscript, ClosingTranscript)

    def publish(self) -> TranscriptState:
        return LiveTranscript()


class LiveTranscript(TranscriptState):
    can_draw = True
    reports_coverage = True
    accepts_source_work = True

    def blocks_visible_read(self, owner: TranscriptSourcePreparation) -> bool:
        return NEWER_END.visible_more(owner) or not self.source_ready(owner)

    def reserve(self, owner, operation: type[WorkingTranscript] | None = None) -> WorkingTranscript:
        return (operation or WorkingTranscript)(self, owner)

    def request_latest(self, owner: TranscriptSourcePreparation, request: LatestViewportRequest) -> None:
        owner.schedule_source_work(partial(owner.jump_latest, request))

    def check_edges(self, owner) -> None:
        if self.source_ready(owner):
            owner.window.lookahead.prepare_source(owner)

    @classmethod
    def successors(cls):
        return (LiveTranscript, ParkedSourceTranscript, DetachedTranscript, ClosingTranscript)

    def publish(self) -> TranscriptState:
        return self


class UnboundTranscript(ProvisionalTranscript):
    """A real local tab has no saved source and starts no page reads."""

    def mounted(self, owner) -> None:
        owner.call_after_refresh(owner.view.retire_loading_splash)


class UnreadTranscript(ProvisionalTranscript, LiveTranscript):
    """Accept first-page work without claiming saved coverage before publication."""

    reports_coverage = False

    def mounted(self, owner: LineHistory) -> None:
        owner.call_after_refresh(owner.load_initial_page)

    def rows_published(self, owner) -> None:
        owner.publish_committed()
        transcript = owner.view.transcript
        transcript.binding.painted(transcript, owner.page_source.through)


@dataclass(frozen=True)
class SuspendedTranscript(TranscriptState):
    source: TranscriptState

    def blocks_visible_read(self, owner: TranscriptSourcePreparation) -> bool:
        """A parked or closing source need not paint now."""
        return False

    @property
    def reports_coverage(self) -> bool:
        return self.source.reports_coverage

    def publish(self) -> TranscriptState:
        return self.source.publish()

    @classmethod
    @abstractmethod
    def successors(cls): ...


class LatestViewportState(ABC):
    @abstractmethod
    def resume(self, owner: TranscriptSourcePreparation) -> LatestViewportState: ...

    def prepare(self, owner: TranscriptSourcePreparation) -> None:
        """No pending destination needs another preparation frame."""


class NoLatestRequest(LatestViewportState):
    def resume(self, owner: TranscriptSourcePreparation) -> LatestViewportState:
        return self


@dataclass(frozen=True)
class LatestViewportRequest(LatestViewportState):
    destination: LatestPosition

    @contextmanager
    def reading(self, owner):
        with ResourceRelease() as release:
            yield owner.page_source, release

    async def page(self, owner: TranscriptSourcePreparation, source: PreparedPageSource):
        return await source.latest(owner.pages[-1].prepared)

    def current(self, window: HistoryWindow) -> bool:
        return self.destination.current(window)

    def restore(self, window: HistoryWindow) -> None:
        self.destination.restore(window)

    def apply(self, owner: TranscriptSourcePreparation) -> None:
        if self.current(owner.window):
            owner.state.request_latest(owner, self)

    def defer(self, owner: TranscriptSourcePreparation) -> LatestViewportState:
        """Keep only the reader's still-current destination for another draw."""
        return self if self.current(owner.window) else NoLatestRequest()

    def prepare(self, owner: TranscriptSourcePreparation) -> None:
        owner.request_preparation()

    def resume(self, owner: TranscriptSourcePreparation) -> LatestViewportState:
        """Return the request state after this draw's source-work admission."""
        if not self.current(owner.window) or owner.schedule_source_work(partial(owner.jump_latest, self)):
            return NoLatestRequest()
        return self


@dataclass(frozen=True)
class ReplacementViewportRequest(LatestViewportRequest):
    """The request owns its new reading until the pages replace the old ones."""

    @abstractmethod
    def source(self, owner: ConversationHistory):
        """Open the complete reading selected by this replacement."""

    @contextmanager
    def reading(self, owner: ConversationHistory):
        with ResourceRelease() as release:
            source = self.source(owner)
            release.callback(source.close)
            yield source, release

    async def page(self, owner: TranscriptSourcePreparation, source: PreparedPageSource):
        return await source.get(PageRequest(OLDER_END, source.through))


@dataclass(frozen=True)
class LatestReplacementViewportRequest(ReplacementViewportRequest):
    through: TranscriptCursor | WireCut

    def source(self, owner: ConversationHistory):
        return owner.page_source.replacement(self.through)


@dataclass(frozen=True)
class PreparedReplacementViewportRequest(ReplacementViewportRequest):
    """An existing prepared page needs no storage read, including closed sources."""

    initial: PreparedTranscriptPage

    def source(self, owner: ConversationHistory):
        return owner.page_source.replacement(self.initial.page.after)

    async def page(self, owner: TranscriptSourcePreparation, source: PreparedPageSource):
        return self.initial.for_view()


@dataclass(frozen=True, eq=False)
class WaitingSourceWork[Result]:
    """The pager's observation keeps one paused operation alive until release."""

    owner: TranscriptSourcePreparation
    snapshot: HistorySourceSnapshot
    work: Callable[[], Awaitable[Result]]
    state: WorkingTranscript

    @contextmanager
    def observe(self):
        from toad.widgets.conversation import Conversation

        scope = self.owner.query_ancestor(Conversation).transcript.binding.thread_scope
        with self.owner.app.coordination_access.observe_thread_changes(self.owner, scope, self.resume):
            yield self

    def resume(self, _event: ThreadRowsChanged) -> None:
        self.owner._source_observation.close()
        if self.snapshot.current(self.owner) and self.owner._source_state is self.state:
            self.state.schedule(self.owner, self.work)
        else:
            self.owner.finish_source_work(self.state)


class WorkingTranscript(SuspendedTranscript):
    """One source update; only this operation can finish its work."""

    def __init__(self, source: TranscriptState, owner):
        super().__init__(source)
        self.window_before = owner.paging_window()
        # Progress since work began and time since the last publication differ:
        # one operation may deliver several readable viewports.
        self.delivery_window = self.window_before
        self.delivery_started = monotonic()
        self.reader_revision = owner.window.scroll_revision
        # The screen asked for rows beyond an edge while this work held the source.
        self.edges_wait = False

    def rows_published(self, owner: TranscriptSourcePreparation) -> None:
        self.source.rows_published(owner)

    def blocks_visible_read(self, owner: TranscriptSourcePreparation) -> bool:
        """A running source operation must finish before its cursor is read."""
        return True

    def progressed(self, owner) -> bool:
        """Source publication or original reader intent may need another edge.

        Native restoration does not advance the reader revision. Unchanged
        reads cannot spin, but movement during I/O must not be discarded merely
        because the source rows and edges stayed unchanged.
        """
        return (
            self.edges_wait
            or self.window_before != owner.paging_window()
            or self.reader_revision != owner.window.scroll_revision
        )

    def delivered(self, owner) -> None:
        window = owner.paging_window()
        if window != self.delivery_window:
            now = monotonic()
            owner.window.lookahead.delivered(now - self.delivery_started)
            self.delivery_window, self.delivery_started = window, now

    def request_latest(self, owner: TranscriptSourcePreparation, request: LatestViewportRequest) -> None:
        owner.supersede_source_work(self, request)

    def check_edges(self, owner: TranscriptSourcePreparation) -> None:
        # One work at a time holds the source. The check is made again when
        # this work ends, even if it changed nothing itself.
        self.edges_wait = True

    def retirement_source(self) -> TranscriptState:
        # Cancellation ends this operation; a parked pager resumes its source,
        # not an operation whose worker has already been retired.
        return self.source.retirement_source()

    @property
    def can_draw(self) -> bool:
        return self.source.can_draw

    @classmethod
    def successors(cls):
        return (LiveTranscript, ProvisionalTranscript, RetiredSourceTranscript, ClosingTranscript, DetachedTranscript)

    def defer_source_work[Result](
        self, owner: TranscriptSourcePreparation, work: Callable[[], Awaitable[Result]]
    ) -> None:
        """The existing observation scope owns the paused operation's lifetime."""
        waiting = WaitingSourceWork(owner, owner.source_snapshot(), work, self)
        owner._source_observation.close()
        owner._source_observation.enter_context(waiting.observe())

    async def execute[Result](self, owner, work: Callable[[], Awaitable[Result]]) -> Result | Literal[False]:
        from agent_comms.coordination_errors import (
            CoordinationReadUnavailable,
            StaleRevision,
        )

        with ExitStack() as completion:
            completion.callback(owner.finish_source_work, self)
            try:
                result = await work()
                if owner._source_state is self:
                    # Generic publications and incremental edge delivery share
                    # this operation's commit; completion cannot count an
                    # already-delivered page again as a new latency sample.
                    self.delivered(owner)
                return result
            except CoordinationReadUnavailable:
                # The same operation stays paused until the existing
                # observer resumes it. Settling it here would schedule another
                # edge read on the next frame before storage is available.
                self.defer_source_work(owner, work)
                completion.pop_all()
                return False
            except StaleRevision:
                # This update could not use its original read. Keep the
                # committed source; a new request owns any later advance.
                return False
            except (OSError, ValueError) as error:
                owner.source_failed(error)
                return False

    def schedule[Result](self, owner, work: Callable[[], Awaitable[Result]]) -> Worker[Result | Literal[False]]:
        return owner.run_worker(partial(self.execute, owner, work))


class DetachedTranscript(SuspendedTranscript):
    @classmethod
    def successors(cls):
        return (LiveTranscript, ProvisionalTranscript)


class ClosingTranscript(SuspendedTranscript):
    @classmethod
    def successors(cls):
        return (DetachedTranscript,)


class RetiredProjectionTranscript(SuspendedTranscript):
    """A filtered view whose owning publication is no longer current."""

    @classmethod
    def successors(cls):
        return (DetachedTranscript,)


class RetiredSourceTranscript(SuspendedTranscript):
    """A departing pager no longer publishes or owns source coverage."""

    reports_coverage = False

    @classmethod
    def successors(cls):
        return (ClosingTranscript, DetachedTranscript)

    def publish(self) -> TranscriptState:
        raise RuntimeError("A retired source pager cannot publish again")


class ParkedSourceTranscript(SuspendedTranscript):
    """A mounted warm pager remains inert until its native source is checked."""

    reports_coverage = False

    @classmethod
    def successors(cls):
        return (LiveTranscript, ClosingTranscript, DetachedTranscript)

    def publish(self) -> TranscriptState:
        raise RuntimeError("A parked source pager cannot publish before validation")

    def retirement_source(self) -> TranscriptState:
        return self.source.retirement_source()

    def retire_preparation(self, owner: TranscriptSourcePreparation) -> None:
        """Parking retains data-only work under the shared runtime's budget.

        Publication and speculative workers are revoked by the pager lifetime;
        the same source revision can reuse its prepared pages after validation.
        Replacement and final disposal still close the original scope.
        """

    def resume(self) -> TranscriptState:
        return self.source

    def resume_if_parked(self, owner: TranscriptSourcePreparation) -> None:
        owner.resume_source()

    def validate_snapshot(self, owner: TranscriptSourcePreparation, page: TranscriptPage) -> None:
        # The publication already holds a certified current source page. Its
        # native/assigned cursor, not rendered content, validates this resource.
        if owner.page_source.accepts_commit(page.after):
            owner.resume_source()


class CommitTranscript(WorkingTranscript):
    """A commit's advance: its saved rows replace the live blocks captured with its page.

    The live blocks leave in the same tree change that draws the last saved
    row, so no frame shows both copies of the turn, or neither.
    """

    def __init__(self, source: TranscriptState, owner, live_blocks: tuple[Widget, ...]):
        from textual.await_complete import AwaitComplete

        super().__init__(source, owner)
        self.live_blocks = live_blocks
        self.claims = tuple(cast("CommitParticipant", block).commit_claim for block in live_blocks)
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
        if self.live_blocks and not NEWER_END.visible_more(owner):
            blocks, self.live_blocks = self.live_blocks, ()
            view = owner.view
            self.retirement = view.transcript.retire_presentations(view.contents, view.output, blocks)
