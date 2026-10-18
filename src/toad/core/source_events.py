"""Source publications carry data; the subscription owns native resources."""

from dataclasses import dataclass

import agent_comms.transcript_events as transcript_events
from .events import CoreEvent


@dataclass(frozen=True)
class CurrentWorkingDirectoryChanged(CoreEvent):
    path: str


@dataclass(frozen=True)
class CommandComplete(CoreEvent):
    return_code: int


@dataclass(frozen=True)
class TranscriptSourceWorkFinished(CoreEvent):
    """The original source released its accepted mutation resource."""


@dataclass(frozen=True)
class TranscriptCoverage(CoreEvent, transcript_events.TranscriptCoverage):
    """Publishes what a committed history covers."""
