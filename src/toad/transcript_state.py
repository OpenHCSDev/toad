"""Transcript publication states and the single Textual lifecycle boundary."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.declared_family import DeclaredFamily
from agent_comms.lifecycle import LifecycleState
from textual.widget import Widget


class TranscriptState(DeclaredFamily, LifecycleState, affix="Transcript"):
    accepts_publication: ClassVar[bool] = False
    reports_coverage: ClassVar[bool] = False
    accepts_source_work: ClassVar[bool] = False

    async def execute(self, owner, work):
        raise RuntimeError("The transcript source has no admitted operation")

    def reserve(self) -> "WorkingTranscript":
        raise RuntimeError("The transcript source cannot admit another operation")

    def request_latest(self, owner) -> None:
        """Inactive source cases cannot admit a destination request."""

    def retirement_source(self) -> "TranscriptState":
        return self

    def resume_if_parked(self, owner) -> None:
        """Resource reveal cannot admit work from an inactive source."""

    def observed(self, widget: Widget) -> "TranscriptState":
        # Textual sets these before dispatching Prune/Unmount, including when
        # an ancestor is removed. Decode at this framework boundary so an
        # async page cannot publish during that interval. They are framework
        # facts, never independent fields maintained by TranscriptHistory.
        if widget._closing:
            return ClosingTranscript(self)
        if widget._pruning:
            return PruningTranscript(self)
        if not widget.is_attached:
            return DetachedTranscript(self)
        return self

    def for_projection(self, projection, owner) -> "TranscriptState":
        """A view may publish only while its source still owns that projection."""
        if owner is None or not owner.state.accepts_publication or not owner.filter.owns_projection(projection):
            return RetiredProjectionTranscript(self)
        return self

    @abstractmethod
    def publish(self) -> "TranscriptState": ...


class ProvisionalTranscript(TranscriptState):
    @classmethod
    def successors(cls):
        return (LiveTranscript, DetachedTranscript, PruningTranscript, ClosingTranscript)

    def publish(self) -> TranscriptState:
        return LiveTranscript()


class LiveTranscript(TranscriptState):
    accepts_publication = True
    reports_coverage = True
    accepts_source_work = True

    def reserve(self) -> "WorkingTranscript":
        return WorkingTranscript(self)

    def request_latest(self, owner) -> None:
        owner.reserve_source_work().schedule(owner, owner._jump_latest)

    @classmethod
    def successors(cls):
        return (LiveTranscript, ParkedSourceTranscript, DetachedTranscript,
                PruningTranscript, ClosingTranscript)

    def publish(self) -> TranscriptState:
        return self


@dataclass(frozen=True)
class SuspendedTranscript(TranscriptState):
    source: TranscriptState

    @property
    def reports_coverage(self) -> bool:
        return self.source.reports_coverage

    def publish(self) -> TranscriptState:
        return self.source.publish()

    @classmethod
    @abstractmethod
    def successors(cls): ...


class ViewportRequest(DeclaredFamily, affix="ViewportRequest"):
    """One bounded destination intent belonging to an admitted operation."""

    @abstractmethod
    def apply(self, owner) -> None: ...


class IdleViewportRequest(ViewportRequest):
    def apply(self, owner) -> None:
        pass


@dataclass(frozen=True)
class LatestViewportRequest(ViewportRequest):
    revision: int

    def apply(self, owner) -> None:
        if owner.window.scroll_revision == self.revision:
            owner.request_latest()


class WorkingTranscript(SuspendedTranscript):
    """One admitted source mutation; its identity owns completion custody."""

    def __init__(self, source: TranscriptState):
        super().__init__(source)
        # The inherited source snapshot stays immutable. Only this operation's
        # bounded pending resource changes, never a second history-level flag.
        self.pending_request: ViewportRequest = IdleViewportRequest()

    def request_latest(self, owner) -> None:
        self.pending_request = LatestViewportRequest(owner.window.scroll_revision)

    def retirement_source(self) -> TranscriptState:
        # Cancellation ends this operation; a parked pager resumes its source,
        # not an operation whose worker has already been retired.
        return self.source.retirement_source()

    @property
    def accepts_publication(self) -> bool:
        return self.source.accepts_publication

    @classmethod
    def successors(cls):
        return (LiveTranscript, ProvisionalTranscript, RetiredSourceTranscript,
                PruningTranscript, ClosingTranscript, DetachedTranscript)

    async def execute(self, owner, work):
        from agent_comms.coordination_errors import StaleRevision

        try:
            return await work()
        except StaleRevision:
            # This admitted mutation declined its original read. Keep the
            # already committed source; a new request owns any later advance.
            return False
        finally:
            owner.finish_source_work(self)

    def schedule(self, owner, work):
        return owner.run_worker(self.execute(owner, work))


class DetachedTranscript(SuspendedTranscript):
    @classmethod
    def successors(cls):
        return (LiveTranscript, ProvisionalTranscript)


class PruningTranscript(SuspendedTranscript):
    @classmethod
    def successors(cls):
        return (ClosingTranscript, DetachedTranscript)


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

    def resume(self) -> TranscriptState:
        return self.source

    def resume_if_parked(self, owner) -> None:
        owner.resume_source()
