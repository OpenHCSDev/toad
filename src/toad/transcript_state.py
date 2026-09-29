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

    @classmethod
    def successors(cls):
        return (LiveTranscript, DetachedTranscript, PruningTranscript, ClosingTranscript)

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


class WorkingTranscript(SuspendedTranscript):
    """One admitted source mutation; its identity owns completion custody."""

    @property
    def accepts_publication(self) -> bool:
        return self.source.accepts_publication

    @classmethod
    def successors(cls):
        return (LiveTranscript, ProvisionalTranscript, RetiredSourceTranscript,
                PruningTranscript, ClosingTranscript, DetachedTranscript)

    async def execute(self, owner, work):
        try:
            return await work()
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
