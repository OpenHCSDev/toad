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
