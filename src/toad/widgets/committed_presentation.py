"""Source evidence and viewport intent govern retirement of live presentation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.widget import Widget
from textual.message import Message
from agent_comms.transcript_events import TranscriptEvent, UserTranscript
from agent_comms.acp_extension import InputStartedUpdate

from toad.widgets.presentation_window import protected_presentations

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_fragments import TranscriptFragment


@dataclass(frozen=True)
class CommitEvidence:
    captured: frozenset[Widget]
    sequences: frozenset[int] = frozenset()
    retained_history: Widget | None = None
    native_inputs: frozenset[str] = frozenset()


class TranscriptCoverage(Message):
    """An accepted source publication owns its original message/input identities."""

    def __init__(self, events: tuple[TranscriptEvent, ...], history=None):
        super().__init__()
        self.events, self.history = events, history

    @property
    def sequences(self) -> frozenset[int]:
        from toad.transcript_preparation import incoming_sequences
        return incoming_sequences(self.events)

    @property
    def native_inputs(self) -> frozenset[str]:
        return frozenset(native_id for event in self.events for native_id in event.native_inputs)


class CommitClaim(ABC):
    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset()

    def represents_input(self, input_id: str) -> bool:
        return False

    @abstractmethod
    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        pass


class CapturedClaim(CommitClaim):
    """A settled source-owned block captured before the snapshot read."""

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return widget in evidence.captured and widget is not evidence.retained_history


@dataclass(frozen=True)
class SequenceClaim(CommitClaim):
    """A wire notice needs its exact persisted counterpart, not a save signal."""

    sequence: int | None

    @property
    def required_sequences(self) -> frozenset[int]:
        return frozenset((self.sequence,)) if self.sequence is not None and self.sequence > 0 else frozenset()

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.sequence is not None and self.sequence in evidence.sequences


class NativeInputClaim(CommitClaim):
    """An original started input retires only against its saved native identity."""

    @property
    @abstractmethod
    def native_id(self) -> str | None: ...

    def covered(self, widget: Widget, evidence: CommitEvidence) -> bool:
        return self.native_id in evidence.native_inputs


@dataclass(frozen=True)
class StartedInputClaim(NativeInputClaim):
    """The original native start receipt owns request and journal identity."""

    source: InputStartedUpdate

    @property
    def native_id(self):
        return self.source.native_id

    def represents_input(self, input_id: str) -> bool:
        return self.source.input_id == input_id


@dataclass(frozen=True)
class TranscriptInputClaim(NativeInputClaim):
    source: UserTranscript

    @property
    def native_id(self):
        return self.source.native_id


class CommitParticipant:
    """Nominal widget contract; unrelated/local widgets are retained by default."""

    @property
    def commit_claim(self) -> CommitClaim:
        raise NotImplementedError


class SnapshotPresentation(CommitParticipant):
    @property
    def commit_claim(self) -> CommitClaim:
        return CAPTURED_CLAIM


class CheckpointBarrier:
    """A local interactive session whose ordering cannot be replaced by a snapshot."""


CAPTURED_CLAIM = CapturedClaim()


class CommittedHistory(SnapshotPresentation):
    """A presentation that retains access to an authoritative source frontier."""

    @property
    def committed_cursor(self) -> TranscriptCursor:
        raise NotImplementedError

    @property
    def checkpoint_available(self) -> bool:
        raise NotImplementedError

    def accepts_commit(self, cursor: TranscriptCursor) -> bool:
        previous = self.committed_cursor
        return cursor.contains(previous)

    async def advance_committed(self, through: TranscriptCursor, is_current: Callable[[], bool]) -> bool:
        raise NotImplementedError

    def retain_committed(self, through: TranscriptCursor) -> None:
        raise NotImplementedError

    def covers_incoming(self, sequence: int) -> bool:
        raise NotImplementedError

    def covered_sequences(self, sequences: frozenset[int]) -> frozenset[int]:
        return frozenset(sequence for sequence in sequences if self.covers_incoming(sequence))



def retirement_candidates(widgets: Iterable[Widget], evidence: CommitEvidence) -> list[Widget]:
    return [widget for widget in widgets
            if isinstance(widget, CommitParticipant) and widget.commit_claim.covered(widget, evidence)]


def required_sequences(widgets: Iterable[Widget]) -> frozenset[int]:
    return frozenset(sequence for widget in widgets if isinstance(widget, CommitParticipant)
                     for sequence in widget.commit_claim.required_sequences)


def protected_blocks(view: Conversation, candidates: Iterable[Widget]) -> set[Widget]:
    endpoints = set(view.screen.selections)
    if view.screen.focused is not None:
        endpoints.add(view.screen.focused)
    if view.cursor_block is not None:
        endpoints.add(view.cursor_block)
    return protected_presentations(candidates, endpoints)


@dataclass(frozen=True)
class PreparedCommit:
    history: CommittedHistory | None
    fragments: tuple[TranscriptFragment, ...] | None
    sequences: frozenset[int]


class CheckpointPlan(ABC):
    """A viewport-owned policy; the coordinator does not branch on block types."""

    def __init__(self, window: HistoryWindow) -> None:
        self.revision = window.scroll_revision

    @abstractmethod
    def current(self, window: HistoryWindow) -> bool:
        pass

    def permits(self, view: Conversation, candidates: Iterable[Widget]) -> bool:
        return not protected_blocks(view, candidates)

    def ready(self, history: CommittedHistory | None) -> bool:
        return history is None or history.checkpoint_available

    @abstractmethod
    async def prepare(self, view: Conversation, history: CommittedHistory | None,
                      page: TranscriptPage, captured: tuple[Widget, ...],
                      is_current: Callable[[], bool]) -> PreparedCommit | None:
        pass

    def commit(self, prepared: PreparedCommit, cursor: TranscriptCursor) -> None:
        """Apply source metadata only after the final retirement checks."""

    def anchor(self, prepared: PreparedCommit) -> Widget | None:
        return None

    @asynccontextmanager
    async def publication(self, view: Conversation, prepared: PreparedCommit):
        async with view.window.preserve_history(self.anchor(prepared)):
            yield

    def finish(self, view: Conversation, cursor: TranscriptCursor) -> None:
        """A retained viewport does not claim that newer records were painted."""


class FollowTailCheckpoint(CheckpointPlan):
    def current(self, window: HistoryWindow) -> bool:
        return window.follows_tail and window.scroll_revision == self.revision

    async def prepare(self, view, history, page, captured, is_current):
        from toad.transcript_preparation import incoming_sequences
        from toad.render_tasks import TranscriptRenderTask
        from toad.work_preparation import RenderPreparation

        if history is not None and history.accepts_commit(page.after):
            if not await history.advance_committed(page.after, is_current):
                return None
            return PreparedCommit(history, None, incoming_sequences(page.events)
                                  | history.covered_sequences(required_sequences(captured)))
        fragments = await view.app.preparation.submit(
            RenderPreparation(TranscriptRenderTask(page.events))
        )
        return PreparedCommit(None, fragments, incoming_sequences(page.events))

    def finish(self, view, cursor):
        view.transcript.painted(cursor)
        view.call_after_refresh(self.restore_reader, view.window)

    def restore_reader(self, window):
        # The publication's captured intent owns its deferred layout effect as
        # well. A later scroll or source return cannot inherit an older anchor.
        if self.current(window):
            window.anchor()


class RetainViewportCheckpoint(CheckpointPlan):
    def __init__(self, window: HistoryWindow) -> None:
        super().__init__(window)
        self.scroll_y = window.scroll_y

    def current(self, window: HistoryWindow) -> bool:
        return (not window.follows_tail and window.scroll_revision == self.revision
                and window.scroll_y == self.scroll_y)

    def ready(self, history: CommittedHistory | None) -> bool:
        return history is not None and history.checkpoint_available

    def permits(self, view, candidates):
        candidates = tuple(candidates)
        if not super().permits(view, candidates):
            return False
        # Hidden tabs have no exposed viewport. Never request offscreen geometry
        # (which could rebuild the whole scene) to decide retirement.
        if not view.screen.is_current:
            return True
        visible = view.screen._compositor.visible_widgets
        viewport = view.window.content_region
        return not any(widget in visible and visible[widget][0].overlaps(viewport)
                       for widget in candidates)

    async def prepare(self, view, history, page, captured, is_current):
        from toad.transcript_preparation import incoming_sequences

        if (history is None or not history.accepts_commit(page.after)
                or not history.checkpoint_available):
            return None
        required = required_sequences(captured)
        known = incoming_sequences(page.events) | history.covered_sequences(required)
        covered = frozenset(sequence for sequence in required
                            if page.after.covers_incoming(sequence))
        return PreparedCommit(history, None, known | covered)

    def commit(self, prepared, cursor):
        assert prepared.history is not None
        prepared.history.retain_committed(cursor)

    def anchor(self, prepared):
        return prepared.history


def checkpoint_plan(window: HistoryWindow) -> CheckpointPlan:
    return FollowTailCheckpoint(window) if window.follows_tail else RetainViewportCheckpoint(window)
