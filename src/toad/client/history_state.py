"""Transcript publication states: the source operation lifecycle, its work and latest-position
requests. Native widgets, workers and DOM lookups stay on the owner passed in."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
import http.client
from time import monotonic
from typing import ClassVar, Literal

from agent_comms.coordination.errors import CoordinationReadUnavailable, ReadAgain
from agent_comms.errors import RouteChangedError
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.lifecycle import LifecycleState
from agent_comms.transcript.transcripts import TranscriptPage
from agent_comms.ui_model.observation import ObserverUnattached
from agent_comms.ui_model.observation_wire import ObservationEnded

from toad.client.history_coverage import NO_COVERAGE, PAGE_COVERAGE, HistoryCoverage
from toad.client.history_preparation import NEWER_END, OLDER_END, PageRequest
from toad.client.resource_release import ResourceRelease
from toad.client.subscribers import CoreObserver

# Network drops, route changes, observer restarts and remote socket failures are recoverable
# outages, never permanent source corruption: defer the operation so CoordinationObserved
# resumes it when connectivity returns instead of retiring the tab into RetiredSourceTranscript.
TRANSIENT_SOURCE_ERRORS = (
    CoordinationReadUnavailable,
    ObservationEnded,
    ObserverUnattached,
    RouteChangedError,
    OSError,
    http.client.HTTPException,
)


class TranscriptState(DeclaredFamily, LifecycleState, affix="Transcript"):
    can_draw: ClassVar[bool] = False
    coverage: ClassVar[HistoryCoverage] = NO_COVERAGE
    accepts_source_work: ClassVar[bool] = False

    def source_ready(self, owner) -> bool:
        """The source accepts work and the filter is not scanning."""
        return self.accepts_source_work and owner.filter.idle

    def schedule_work(self, owner, work) -> SourceWork:
        """A source that takes no work defers it; the caller decides whether to retry."""
        return DEFERRED_WORK

    def blocks_visible_read(self, owner) -> bool:
        """An unpublished source must settle before its cursor is read."""
        return True

    async def execute[Result](
        self, owner, work: Callable[[], Awaitable[Result]]
    ) -> Result | Literal[False]:
        raise RuntimeError("No transcript source operation is running")

    def reserve(
        self, owner, operation: type[WorkingTranscript] | partial[WorkingTranscript]
    ) -> WorkingTranscript:
        raise RuntimeError("The transcript source cannot start another operation")

    def request_latest(self, owner, request: LatestViewportRequest) -> None:
        """An inactive source starts no destination request."""

    def check_edges(self, owner) -> None:
        """A source that takes no work draws nothing beyond its edges."""

    def delivered(self, owner) -> None:
        """Only a running source operation measures time to publication."""

    def arriving(self, prepared, followed_end: bool):
        """The staged range begins at the edge this append advances."""
        return prepared.fragments[prepared.start : prepared.stop] if followed_end else ()

    def mounted(self, owner) -> None:
        """An already-read source needs no initial destination request."""

    def rows_published(self, owner) -> None:
        """Only a commit's advance has live blocks that its saved rows replace."""

    def retirement_source(self) -> TranscriptState:
        return self

    def retire_preparation(self, owner) -> None:
        """Final source retirement releases its bounded prepared-page scope."""
        owner.close()

    def resume(self) -> TranscriptState:
        raise RuntimeError("Only a parked transcript can resume publication")

    def resume_if_parked(self, owner) -> None:
        """Showing a resource does not start work on an inactive source."""

    def validate_snapshot(self, owner, page: TranscriptPage) -> None:
        """A captured source page may validate its existing parked resource."""

    def observed(self, widget: CoreObserver) -> TranscriptState:
        # Textual sets these before dispatching Prune/Unmount, including when
        # an ancestor is removed. Decode at this framework boundary so an
        # async page cannot publish during that interval. They are framework
        # facts, never independent fields maintained by TranscriptHistory.
        if widget.is_leaving:
            return ClosingTranscript(self)
        if not widget.is_attached:
            return DetachedTranscript(self)
        return self

    def for_projection(self, projection, owner) -> TranscriptState:
        """A view may publish only while its source still draws that projection."""
        return self if owner.draws_projection(projection) else RetiredProjectionTranscript(self)

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
    coverage: ClassVar[HistoryCoverage] = PAGE_COVERAGE
    accepts_source_work = True

    def blocks_visible_read(self, owner) -> bool:
        return NEWER_END.visible_more(owner) or not self.source_ready(owner)

    def reserve(self, owner, operation) -> WorkingTranscript:
        return operation(self, owner)

    def request_latest(self, owner, request: LatestViewportRequest) -> None:
        owner.schedule_source_work(partial(owner.jump_latest, request))

    def schedule_work(self, owner, work) -> SourceWork:
        return RunningSourceWork(owner.reserve_source_work().schedule(owner, work))

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

    coverage = NO_COVERAGE

    def mounted(self, owner) -> None:
        owner.call_after_refresh(owner.load_initial_page)

    def rows_published(self, owner) -> None:
        owner.publish_committed()
        transcript = owner.view.transcript
        transcript.binding.painted(transcript, owner.page_source.through)


@dataclass(frozen=True)
class SuspendedTranscript(TranscriptState):
    source: TranscriptState

    def blocks_visible_read(self, owner) -> bool:
        """A parked or closing source need not paint now."""
        return False

    @property
    def coverage(self) -> HistoryCoverage:
        return self.source.coverage

    def publish(self) -> TranscriptState:
        return self.source.publish()

    @classmethod
    def successors(cls):
        return (DetachedTranscript,)


class SourceWork(ABC):
    """What became of work handed to a transcript's source: running on its pager worker, or deferred."""

    @abstractmethod
    def latest_after(self, request: LatestViewportState) -> LatestViewportState:
        """The latest-position request left once this work was handed over."""

    @abstractmethod
    async def waited(self) -> bool:
        """Wait for running work and answer True; deferred work answers False at once."""


@dataclass(frozen=True)
class RunningSourceWork[Work](SourceWork):
    worker: Work

    def latest_after(self, request: LatestViewportState) -> LatestViewportState:
        return NoLatestRequest()

    async def waited(self) -> bool:
        await self.worker.wait()
        return True


class DeferredSourceWork(SourceWork):
    def latest_after(self, request: LatestViewportState) -> LatestViewportState:
        return request

    async def waited(self) -> bool:
        return False


DEFERRED_WORK = DeferredSourceWork()


class LatestViewportState(ABC):
    @abstractmethod
    def resume(self, owner) -> LatestViewportState: ...

    def prepare(self, owner) -> None:
        """No pending destination needs another preparation frame."""


class NoLatestRequest(LatestViewportState):
    def resume(self, owner) -> LatestViewportState:
        return self


@dataclass(frozen=True)
class LatestViewportRequest[Destination](LatestViewportState):
    destination: Destination

    @contextmanager
    def reading(self, owner):
        with ResourceRelease() as release:
            yield owner.page_source, release

    async def page(self, owner, source):
        return await source.latest(owner.pages[-1].prepared)

    def current(self, window) -> bool:
        return self.destination.current(window)

    def restore(self, window) -> None:
        self.destination.restore(window)

    def apply(self, owner) -> None:
        if self.current(owner.window):
            owner.state.request_latest(owner, self)

    def defer(self, owner) -> LatestViewportState:
        """Keep only the reader's still-current destination for another draw."""
        return self if self.current(owner.window) else NoLatestRequest()

    def prepare(self, owner) -> None:
        owner.request_preparation()

    def resume(self, owner) -> LatestViewportState:
        """Return the request state after this draw's source-work admission."""
        if not self.current(owner.window):
            return NoLatestRequest()
        return owner.schedule_source_work(partial(owner.jump_latest, self)).latest_after(self)


@dataclass(frozen=True)
class ReplacementViewportRequest(LatestViewportRequest):
    """The request owns its new reading until the pages replace the old ones."""

    animates_arrivals: ClassVar[bool] = False

    @abstractmethod
    def source(self, owner):
        """Open the complete reading selected by this replacement."""

    @contextmanager
    def reading(self, owner):
        with ResourceRelease() as release:
            source = self.source(owner)
            release.callback(source.close)
            yield source, release

    async def page(self, owner, source):
        return await source.get(PageRequest(OLDER_END, source.through))


@dataclass(frozen=True)
class LatestReplacementViewportRequest[Cursor](ReplacementViewportRequest):
    through: Cursor
    animates_arrivals: ClassVar[bool] = True

    def source(self, owner):
        return owner.page_source.replacement(self.through)


@dataclass(frozen=True)
class PreparedReplacementViewportRequest[Page](ReplacementViewportRequest):
    """An existing prepared page needs no storage read, including closed sources."""

    initial: Page

    def source(self, owner):
        return owner.page_source.replacement(self.initial.page.after)

    async def page(self, owner, source):
        return self.initial.for_view()

    def defer(self, owner) -> LatestViewportState:
        """A commit's page publishes only with its commit, which records the painted cursor and
        retries itself; drawn later on its own, its rows would show a source the cursor never reached."""
        return NoLatestRequest()


@dataclass(frozen=True, eq=False)
class WaitingSourceWork[Owner, Snapshot, Result]:
    """The pager's observation keeps one paused operation alive until release."""

    owner: Owner
    snapshot: Snapshot
    work: Callable[[], Awaitable[Result]]
    state: WorkingTranscript

    @contextmanager
    def observe(self):
        # `PreparedPageSource.observe_availability` watches both the view's thread scope
        # (a no-op on wire conversations whose scope is `NoTranscript`) and Core's
        # coordination stream so reconnection resumes paused transcript and wire reads alike.
        view = self.owner.view
        with self.owner.page_source.observe_availability(
            view, self.owner.app.coordination_access, self.resume
        ):
            yield self

    def resume(self, _event: object) -> None:
        self.owner._source_observation.close()
        if self.snapshot.current(self.owner) and self.owner._source_state is self.state:
            self.state.schedule(self.owner, self.work)
        else:
            self.owner.finish_source_work(self.state)


class ResumableTranscript(SuspendedTranscript, declared_name=None):
    """A temporarily suspended transcript whose retirement unwraps back to its source."""

    def retirement_source(self) -> TranscriptState:
        return self.source.retirement_source()


class WorkingTranscript(ResumableTranscript):
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
        # Work handed over while this held the source, run once it ends (`owed`).
        self.owed: dict[object, Callable[[], Awaitable[object]]] = {}

    def schedule_work(self, owner, work) -> SourceWork:
        """Work arriving while this holds the source runs once it ends, once per kind: a
        refresh reads everything new, so two owed refreshes are one. Returned as deferred, it
        was dropped by callers that never retried, and a burst's last messages stayed unread
        until something else changed (a phone-speed burst left 6 of 20 undrawn)."""
        key = (work.func, work.args) if isinstance(work, partial) else work
        self.owed[key] = work
        return DEFERRED_WORK

    def publish(self) -> TranscriptState:
        """Advance the wrapped state without dropping this running operation before `finish_source_work`."""
        object.__setattr__(self, "source", self.source.publish())
        return self

    def rows_published(self, owner) -> None:
        self.source.rows_published(owner)

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

    @property
    def can_draw(self) -> bool:
        return self.source.can_draw

    @classmethod
    def successors(cls):
        return (LiveTranscript, ProvisionalTranscript, RetiredSourceTranscript, ClosingTranscript, DetachedTranscript)

    def defer_source_work[Result](
        self, owner, work: Callable[[], Awaitable[Result]]
    ) -> None:
        """The existing observation scope owns the paused operation's lifetime."""
        waiting = WaitingSourceWork(owner, owner.source_snapshot(), work, self)
        owner._source_observation.close()
        owner._source_observation.enter_context(waiting.observe())

    async def execute[Result](self, owner, work: Callable[[], Awaitable[Result]]) -> Result | Literal[False]:
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
            except TRANSIENT_SOURCE_ERRORS:
                # The same operation stays paused until the existing observer resumes it
                # on CoordinationObserved / ThreadRowsChanged, and asks CoordinationAccess
                # to check the route so a lost connection recovers without retiring the tab.
                self.defer_source_work(owner, work)
                owner.app.coordination_access.check_route()
                completion.pop_all()
                return False
            except ReadAgain:
                # This update could not use its original read. Keep the
                # committed source; a new request owns any later advance.
                return False
            except Exception as error:
                owner.source_failed(error)
                return False

    def schedule[Result](self, owner, work: Callable[[], Awaitable[Result]]):
        return owner.run_worker(partial(self.execute, owner, work))


class DetachedTranscript(SuspendedTranscript):
    @classmethod
    def successors(cls):
        return (LiveTranscript, ProvisionalTranscript)


class ClosingTranscript(SuspendedTranscript):
    pass


class RetiredProjectionTranscript(SuspendedTranscript):
    """A filtered view whose owning publication is no longer current."""


class RetiredSourceTranscript(SuspendedTranscript):
    """A departing pager no longer publishes or owns source coverage."""

    coverage = NO_COVERAGE

    @classmethod
    def successors(cls):
        return (ClosingTranscript, DetachedTranscript)

    def publish(self) -> TranscriptState:
        raise RuntimeError("A retired source pager cannot publish again")


class ParkedSourceTranscript(ResumableTranscript):
    """A mounted warm pager remains inert until its native source is checked."""

    coverage = NO_COVERAGE

    @classmethod
    def successors(cls):
        return (LiveTranscript, ClosingTranscript, DetachedTranscript)

    def publish(self) -> TranscriptState:
        raise RuntimeError("A parked source pager cannot publish before validation")

    def retire_preparation(self, owner) -> None:
        """Parking retains data-only work under the shared runtime's budget.

        Publication and speculative workers are revoked by the pager lifetime;
        the same source revision can reuse its prepared pages after validation.
        Replacement and final disposal still close the original scope.
        """

    def resume(self) -> TranscriptState:
        return self.source

    def resume_if_parked(self, owner) -> None:
        owner.resume_source()

    def validate_snapshot(self, owner, page: TranscriptPage) -> None:
        # The publication already holds a certified current source page. Its
        # native/assigned cursor, not rendered content, validates this resource.
        if owner.page_source.accepts_commit(page.after):
            owner.resume_source()
