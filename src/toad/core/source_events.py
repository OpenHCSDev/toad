"""Source publications carry data; the subscription owns native resources."""

from dataclasses import dataclass

from agent_comms.transcript_events import TranscriptEvent
from .events import CoreEvent


@dataclass(frozen=True)
class DirectoryChanged(CoreEvent):
    def can_replace(self, event: CoreEvent) -> bool:
        return self == event


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

    @property
    def sequences(self) -> frozenset[int]:
        return frozenset(source.seq for event in self.events
                         for source in event.incoming_sources if source.seq > 0)

    @property
    def native_inputs(self) -> frozenset[str]:
        return frozenset(native_id for event in self.events for native_id in event.native_inputs)
