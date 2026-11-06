"""The claims a live block holds on the source rows that retire it, and the evidence they read."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from agent_comms.acp_extension import InputStartedUpdate
from agent_comms.sent_message import OutgoingMessageReference, PublishedSentMessage
from agent_comms.transcript_events import TranscriptCoverage, TranscriptEvent
from agent_comms.transcripts import NativeCommittedPrefix, TranscriptCursor, TranscriptReadIdentity
from textual.abstract_hooks import AbstractHooksMeta
from textual.widget import Widget


@dataclass(frozen=True)
class CommitEvidence:
    captured: frozenset[Widget]
    sequences: frozenset[int] = frozenset()
    retained_history: Widget | None = None
    native_inputs: frozenset[str] = frozenset()
    outgoing: frozenset[OutgoingMessageReference] = frozenset()

    def covers_native(self, source: NativeCommittedPrefix) -> bool:
        return False


@dataclass(frozen=True, kw_only=True)
class NativeCommitEvidence(CommitEvidence):
    identity: TranscriptReadIdentity

    def covers_native(self, source: NativeCommittedPrefix) -> bool:
        return source.contains_native_prefix(self.identity)


class CommitSource:
    """Uncommitted output needs settlement; a native append supplies exact coverage."""

    def capture(self, settled: bool) -> bool:
        return settled

    def accepts(self, identity: TranscriptReadIdentity) -> bool:
        return True

    def covered(self, evidence: CommitEvidence) -> bool:
        return True

    def prefixes(self, identity: TranscriptReadIdentity, cursor: TranscriptCursor) -> tuple[TranscriptCursor, ...]:
        return ()


@dataclass(frozen=True)
class NativeCommitSource(CommitSource):
    original: NativeCommittedPrefix

    def capture(self, settled: bool) -> bool:
        return True

    def accepts(self, identity: TranscriptReadIdentity) -> bool:
        return self.original.contains_native_prefix(identity)

    def covered(self, evidence: CommitEvidence) -> bool:
        return evidence.covers_native(self.original)

    def prefixes(self, identity: TranscriptReadIdentity, cursor: TranscriptCursor) -> tuple[TranscriptCursor, ...]:
        return (self.original.page_bound.with_frontier(cursor.wire),) if self.accepts(identity) else ()

class CommitClaim(ABC):
    # Whether a commit may retire the block holding this claim, and whether the block holds every commit back.
    retires: ClassVar[bool] = True
    blocks_commit: ClassVar[bool] = False

    def capture(self, settled: bool) -> bool:
        return True

    def accepts_native(self, widget: Widget, captured: frozenset[Widget],
                       identity: TranscriptReadIdentity) -> bool:
        return True

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset()

    @abstractmethod
    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        pass

    # Whether the live block already showed a saved row its commit retires it for;
    # a row no live block showed arrives (`CommitTranscript.arriving`).
    def repeats_native(self, events: tuple[TranscriptEvent, ...]) -> bool:
        return False

    def repeats_received(self, events: tuple[TranscriptEvent, ...]) -> bool:
        return False

    def repeats_sent(self, reference: OutgoingMessageReference) -> bool:
        return False

@dataclass(kw_only=True)
class CapturedClaim(CommitClaim):
    """A captured block, sealed by its original append or a settled turn."""

    source: CommitSource = field(default_factory=CommitSource)

    def seal(self, source: NativeCommittedPrefix) -> None:
        self.source = NativeCommitSource(source)

    def capture(self, settled: bool) -> bool:
        return self.source.capture(settled)

    def accepts_native(self, widget: Widget, captured: frozenset[Widget],
                       identity: TranscriptReadIdentity) -> bool:
        return widget in captured and self.source.accepts(identity)

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return (widget in evidence.captured and widget is not evidence.retained_history
                and self.source.covered(evidence))

    def repeats_native(self, events: tuple[TranscriptEvent, ...]) -> bool:
        # The snapshot captured the native output its saved records hold.
        return True

@dataclass
class ToolOutputClaim(CapturedClaim):
    """A compact tool cannot retire before its separate bodies are supplied."""

    outgoing: frozenset[OutgoingMessageReference]

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return super().covered(widget, evidence) and self.outgoing <= evidence.outgoing

    def repeats_sent(self, reference: OutgoingMessageReference) -> bool:
        return reference in self.outgoing

class RetainedSourceClaim(CapturedClaim):
    """An original saved source is transferable independently of live output."""

    def capture(self, settled: bool) -> bool:
        return True

    def accepts_native(self, widget: Widget, captured: frozenset[Widget],
                       identity: TranscriptReadIdentity) -> bool:
        return True

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return widget is not evidence.retained_history

@dataclass(frozen=True)
class SequenceClaim(CommitClaim):
    """A wire notice needs its exact persisted counterpart, not a save signal."""

    sequence: int | None

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset((self.sequence,)) if self.sequence is not None and self.sequence > 0 else frozenset()

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.sequence is not None and self.sequence in evidence.sequences

    def repeats_received(self, events: tuple[TranscriptEvent, ...]) -> bool:
        return self.sequence in TranscriptCoverage(events).sequences

@dataclass(frozen=True)
class OutgoingMessageClaim(CommitClaim):
    message: PublishedSentMessage

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.message.reference in evidence.outgoing

    def repeats_sent(self, reference: OutgoingMessageReference) -> bool:
        return reference == self.message.reference

@dataclass(frozen=True)
class StartedInputClaim(CommitClaim):
    """An original started input retires only against its saved native identity."""

    source: InputStartedUpdate

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.source.native_id in evidence.native_inputs

    def repeats_native(self, events: tuple[TranscriptEvent, ...]) -> bool:
        return self.source.native_id in TranscriptCoverage(events).native_inputs

class CommitParticipant(metaclass=AbstractHooksMeta):
    """Nominal widget contract; unrelated/local widgets are retained by default."""

    @property
    @abstractmethod
    def commit_claim(self) -> CommitClaim:
        ...


class RetainedBlockClaim(CommitClaim):
    """A block that declares no claim: a commit never retires it and captures it as it is."""

    retires = False

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return False


class CommitBarrierClaim(RetainedBlockClaim):
    """A local interactive session whose ordering a snapshot cannot replace: commits wait for it."""

    blocks_commit = True

CAPTURED_CLAIM = CapturedClaim()
RETAINED_SOURCE_CLAIM = RetainedSourceClaim()
