"""Transcript publication states and the single Textual lifecycle boundary."""

from abc import abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
from time import monotonic
from typing import ClassVar, TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.lifecycle import LifecycleState
from textual.widget import Widget

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from toad.transcript_preparation import PreparedPageSource
    from toad.transcript_source_preparation import HistorySourceSnapshot, TranscriptSourcePreparation
    from toad.widgets.history_anchor import LatestPosition


class TranscriptState(DeclaredFamily, LifecycleState, affix="Transcript"):
    can_draw: ClassVar[bool] = False
    reports_coverage: ClassVar[bool] = False
    # Rows appended to the followed end are new to the reader and fade in.
    rows_arrive: ClassVar[bool] = True
    accepts_source_work: ClassVar[bool] = False

    def source_ready(self, owner) -> bool:
        """The source accepts work and the filter is not scanning."""
        return self.accepts_source_work and owner.filter.idle

    def blocks_visible_read(self, owner) -> bool:
        """An unpublished source must settle before its cursor is read."""
        return True

    async def execute(self, owner, work):
        raise RuntimeError("No transcript source operation is running")

    def reserve(self, owner, operation=None) -> "WorkingTranscript":
        raise RuntimeError("The transcript source cannot start another operation")

    def request_latest(self, owner, request: "LatestViewportRequest") -> None:
        """An inactive source starts no destination request."""

    def check_edges(self, owner) -> None:
        """A source that takes no work draws nothing beyond its edges."""

    def delivered(self, owner) -> None:
        """Only a running source operation measures time to publication."""

    def rows_published(self, owner) -> None:
        """Only a commit's advance has live blocks that its saved rows replace."""

    def retirement_source(self) -> "TranscriptState":
        return self

    def retire_preparation(self, preparation: "PreparedPageSource | None") -> None:
        """Final source retirement releases its bounded prepared-page scope."""
        if preparation is not None:
            preparation.close()

    def resume(self) -> "TranscriptState":
        raise RuntimeError("Only a parked transcript can resume publication")

    def resume_if_parked(self, owner) -> None:
        """Showing a resource does not start work on an inactive source."""

    def validate_snapshot(self, owner, page) -> None:
        """A captured source page may validate its existing parked resource."""

    def observed(self, widget: Widget) -> "TranscriptState":
        # Textual sets these before dispatching Prune/Unmount, including when
        # an ancestor is removed. Decode at this framework boundary so an
        # async page cannot publish during that interval. They are framework
        # facts, never independent fields maintained by TranscriptHistory.
        if widget.is_leaving:
            return ClosingTranscript(self)
        if not widget.is_attached:
            return DetachedTranscript(self)
        return self

    def for_projection(self, projection, owner) -> "TranscriptState":
        """A view may publish only while its source still owns that projection."""
        if owner is None or not owner.state.can_draw or not owner.filter.overlay is projection:
            return RetiredProjectionTranscript(self)
        return self

    @abstractmethod
    def publish(self) -> "TranscriptState": ...


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

    def blocks_visible_read(self, owner) -> bool:
        return owner.has_newer or not self.source_ready(owner)

    def reserve(self, owner, operation=None) -> "WorkingTranscript":
        return (operation or WorkingTranscript)(self, owner)

    def request_latest(self, owner, request: "LatestViewportRequest") -> None:
        owner.schedule_source_work(partial(owner._jump_latest, request))

    def check_edges(self, owner) -> None:
        if self.source_ready(owner):
            owner.window.lookahead.prepare_source(owner)

    @classmethod
    def successors(cls):
        return (LiveTranscript, ParkedSourceTranscript, DetachedTranscript,
                ClosingTranscript)

    def publish(self) -> TranscriptState:
        return self


@dataclass(frozen=True)
class SuspendedTranscript(TranscriptState):
    source: TranscriptState

    def blocks_visible_read(self, owner) -> bool:
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


@dataclass(frozen=True)
class LatestViewportRequest:
    destination: "LatestPosition"

    def current(self, window) -> bool:
        return self.destination.current(window)

    def restore(self, window) -> None:
        self.destination.restore(window)

    def apply(self, owner) -> None:
        if self.current(owner.window):
            owner.state.request_latest(owner, self)


@dataclass(frozen=True, eq=False)
class WaitingSourceWork:
    """The pager's observation keeps one paused operation alive until release."""

    owner: "TranscriptSourcePreparation"
    snapshot: "HistorySourceSnapshot"
    work: "Callable[[], Awaitable[object]]"
    state: "WorkingTranscript"

    @contextmanager
    def observe(self):
        from toad.widgets.conversation import Conversation

        scope = self.owner.query_ancestor(Conversation).transcript.thread_scope
        with self.owner.app.coordination_access.observe_thread_changes(
            self.owner, scope, self.resume
        ):
            yield self

    def resume(self, _event) -> None:
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

    def blocks_visible_read(self, owner) -> bool:
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

    def request_latest(self, owner, request: LatestViewportRequest) -> None:
        owner.supersede_source_work(self, request)

    def check_edges(self, owner) -> None:
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
        return (LiveTranscript, ProvisionalTranscript, RetiredSourceTranscript,
                ClosingTranscript, DetachedTranscript)

    def defer_source_work(self, owner, work) -> None:
        """The existing observation scope owns the paused operation's lifetime."""
        waiting = WaitingSourceWork(owner, owner.source_snapshot(), work, self)
        owner._source_observation.close()
        owner._source_observation.enter_context(waiting.observe())

    async def execute(self, owner, work):
        from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision

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

    def schedule(self, owner, work):
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

    def retire_preparation(self, preparation: "PreparedPageSource | None") -> None:
        """Parking retains data-only work under the shared runtime's budget.

        Publication and speculative workers are revoked by the pager lifetime;
        the same source revision can reuse its prepared pages after validation.
        Replacement and final disposal still close the original scope.
        """

    def resume(self) -> TranscriptState:
        return self.source

    def resume_if_parked(self, owner) -> None:
        owner.resume_source()

    def validate_snapshot(self, owner, page) -> None:
        # The publication already holds a certified current source page. Its
        # native/assigned cursor, not rendered content, validates this resource.
        if page.after.contains(owner.through):
            owner.resume_source()


class CommitTranscript(WorkingTranscript):
    """A commit's advance: its saved rows replace the live blocks captured with its page.

    The live blocks leave in the same tree change that draws the last saved
    row, so no frame shows both copies of the turn, or neither.
    """

    def __init__(self, source: TranscriptState, owner, live_blocks: tuple[Widget, ...]):
        super().__init__(source, owner)
        self.live_blocks = live_blocks

    @property
    def rows_arrive(self) -> bool:
        # Rows the reader already saw as live blocks have not arrived again.
        return not self.live_blocks

    def rows_published(self, owner) -> None:
        if not owner.has_newer:
            for block in self.live_blocks:
                block.display = False
