"""Source publications carry data; the subscription owns native resources."""

from dataclasses import dataclass

from agent_comms.transcript_events import TranscriptEvent
from agent_comms.message_reference import AssignedSourceIdentity, OutgoingMessageReference
from .events import CoreEvent


@dataclass(frozen=True)
class CurrentWorkingDirectoryChanged(CoreEvent):
    path: str


@dataclass(frozen=True)
class CommandComplete(CoreEvent):
    return_code: int


@dataclass(frozen=True)
class MessageHandlingRequested(CoreEvent):
    """Request handling publication from the original mounted source."""


@dataclass(frozen=True)
class TranscriptSourceWorkFinished(CoreEvent):
    """The original source released its admitted mutation resource."""


@dataclass(frozen=True)
class TranscriptCoverage(CoreEvent):
    events: tuple[TranscriptEvent, ...]
    scope: AssignedSourceIdentity | None = None

    @classmethod
    def from_page(cls, page):
        return cls(page.events, page.after.receipts.identity)

    @property
    def outgoing(self) -> frozenset[OutgoingMessageReference]:
        return frozenset(source for event in self.events for source in event.outgoing_sources
                         if source.scope == self.scope)

    @property
    def sequences(self) -> frozenset[int]:
        return frozenset(source.seq for event in self.events
                         for source in event.incoming_sources if source.seq > 0)

    @property
    def native_inputs(self) -> frozenset[str]:
        return frozenset(native_id for event in self.events for native_id in event.native_inputs)
