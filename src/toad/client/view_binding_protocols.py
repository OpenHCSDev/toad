"""The surface `BoundView` reaches on its host view, declared once for every frontend.

`BoundView` (transcript_publication.py) owns a conversation view's transcript binding: its
scope, its thread subscription, page and increment delivery, and which transcript blocks
are live, committed or retired. Everything it asks of the toolkit is a member here.
Textual's `Conversation` and Qt's thread views both inherit `BoundViewHost`: Textual's
widgets render the blocks as mounted children, Qt's history model renders them as rows.
A host that leaves a member out fails at class creation (`AbstractHooksMeta`).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import TYPE_CHECKING, ClassVar

from agent_comms.execution.transcript_sources import DraftFold
from metaclass_registry.mro_dispatch import handles

from toad.core.events import Publication
from toad.core.source_events import TranscriptCoverage, TranscriptSourceWorkFinished


if TYPE_CHECKING:
    from agent_comms.execution.transcript_sources import TranscriptCursor
    from agent_comms.transcript.transcript_drafts import NoDraft
    from agent_comms.transcript.transcripts import TranscriptReadIdentity
    from toad.client.prepared_pages import PreparedPageSource, PreparedTranscriptPage
    from toad.client.transcript_history_contract import TranscriptHistoryContract
    from toad.client.session_scope import SessionScope
    from toad.core.events import ThreadRowsChanged
    from toad.transcript_publication import PublicationWork


class BoundViewHost:
    """What `BoundView` requires of its host view. A plain mixin, like the other shared
    view bases: each toolkit's widget metaclass (`AbstractHooksMeta`) refuses a view class
    that leaves one of these abstract."""

    MAX_LIVE_BLOCKS: ClassVar[int]
    """How many live blocks may stand before a refresh commits them into history. A view
    that draws no live blocks sets 1: every refresh commits."""

    @handles(TranscriptSourceWorkFinished)
    def on_transcript_source_work_finished(self, event: TranscriptSourceWorkFinished, message: Publication) -> None:
        """One of this view's histories released its source: the transcript publishes what
        waited for that (`TranscriptPresentation.retry`). Declared here for every frontend:
        Textual's conversation declared it and Qt's thread views did not, so a Qt thread's
        publication that had waited on a page read waited for the next unrelated event."""
        self.transcript.source_work_finished(self)

    @handles(TranscriptCoverage)
    async def on_transcript_coverage(self, event: TranscriptCoverage, message: Publication) -> None:
        """Saved history published what its loaded pages cover: retire covered live blocks
        and announce coverage to Core. Shared by Textual and Qt."""
        message.stop()
        await self.transcript.binding.covered(self.transcript, event, message.publisher)

    def retire_loading_splash(self) -> None:
        """Saved history painted, or failed, or there is none: the splash the view composed
        while it waited goes. A view that composes none has nothing to retire. (Textual's
        conversation composes one; the shared transcript states ask every host, and a Qt
        agent tab raised `AttributeError` at mount: `UnboundTranscript.mounted`.)"""

    # ---- the tree ----

    @property
    @abstractmethod
    def window(self) -> object:
        """The transcript window: its reader position and scroll revision."""

    @property
    @abstractmethod
    def contents(self) -> object:
        """The native container holding the view's transcript blocks; `BoundView.current`
        reads its `is_attached`."""

    @property
    @abstractmethod
    def transcript_history(self) -> TranscriptHistoryContract:
        """The single transcript-page-producing child `BoundView` drives."""

    @abstractmethod
    def query_ancestor(self, kind: type[SessionScope]) -> SessionScope:
        """The enclosing `SessionScope`; `LookupError` when the view has none."""

    @property
    @abstractmethod
    def ancestors(self) -> Iterable[object]:
        """Every ancestor up the tree; `source in view.ancestors` asks whether a scope
        still contains the view."""

    # ---- the thread ----

    @abstractmethod
    def thread_observed(self, event: ThreadRowsChanged) -> None:
        """The observed thread's rows changed: consume its presentation and publish its
        source. `BoundView.observe_thread` subscribes exactly this method."""

    # ---- the blocks, as data ----

    @property
    @abstractmethod
    def live_blocks(self) -> tuple[object, ...]:
        """The view's transcript blocks in order: its committed history, then any live
        blocks after it. `BoundView` decides which are live, committed or retired."""

    @abstractmethod
    def retire_blocks(self, blocks: Sequence[object]) -> Awaitable[None]:
        """Stop drawing these live blocks: history now covers them."""

    @abstractmethod
    def protected_blocks(self, candidates: Iterable[object]) -> set[object]:
        """Of these blocks, the ones a reader is interacting with and that must stay."""

    @abstractmethod
    def blocks_in_viewport(self, candidates: Sequence[object]) -> bool:
        """Whether any of these blocks is on screen now."""

    @abstractmethod
    def show_draft(self, draft: DraftFold | NoDraft, identity: TranscriptReadIdentity) -> None:
        """Draw the thread's in-progress CLI draft after the history, or clear it."""

    @abstractmethod
    def empty_history(self) -> TranscriptHistoryContract:
        """A new history with no source pages yet, for a replaced source."""

    @abstractmethod
    def later_history(
        self, page: PreparedTranscriptPage, source: PreparedPageSource, conversation_order: int
    ) -> TranscriptHistoryContract:
        """A history continuing after an entry placed into this one."""

    @abstractmethod
    def mount_history(
        self, history: TranscriptHistoryContract, *, before: TranscriptHistoryContract | None = None
    ) -> Awaitable[None]:
        """Draw this history among the blocks (after them, or before `before`)."""

    @abstractmethod
    def remove_history(self, history: TranscriptHistoryContract) -> Awaitable[None]:
        """Stop drawing a replaced history."""

    # ---- the native loop ----

    @abstractmethod
    def call_later(self, callback: Callable[..., object], *args: object) -> bool:
        """Run `callback` on the native loop after the work already queued there."""

    @abstractmethod
    def after_refresh(self, callback: Callable[[], object]) -> None:
        """Run `callback` once the native view has drawn its pending changes."""

    @abstractmethod
    def on_native_pump(self) -> bool:
        """Whether the running task is the native loop that applies this view's messages."""

    @abstractmethod
    async def native_applied(self) -> bool:
        """Wait until the native loop has applied the messages queued before now; False
        when the view stopped running before it did."""

    @abstractmethod
    def start_publication(self, task: Callable[[], Awaitable[object]], *, exclusive: bool) -> PublicationWork:
        """Run a publication on the native loop; an exclusive one supersedes its kind."""

    @abstractmethod
    def cancel_publications(self) -> tuple[PublicationWork, ...]:
        """Cancel this view's running publications and return them to join."""

    @abstractmethod
    def current_publication(self) -> object:
        """The running publication's handle, as `PublicationWork.runs` compares it."""

    @abstractmethod
    def join_completion(self, completion: object) -> None:
        """Observe an optional completion once it finishes without occupying the native pump."""

    # ---- what a publication tells the view ----

    def history_painted(self) -> None:
        """A publication painted the history. One sequence for every frontend: the view does
        what is its own (`view_painted`), the application hears a history is displayed (the
        process's heap freezes at the first), and submissions waiting on drawn rows settle.

        Each frontend's view wrote this sequence itself until 2026-11-22, and Qt's had no
        `history_displayed` in it: its heap was never frozen after startup, and nothing said
        so until the two overrides were compared (NRA's sibling-override-step finding)."""
        self.view_painted()
        self.app.history_displayed()
        self.submissions.settle()

    def view_painted(self) -> None:
        """What this frontend's view does of its own once its history is painted: nothing,
        unless it drew something while the history loaded or tells an ancestor."""

    @abstractmethod
    def refresh_session_summary(self) -> None:
        """Retired or revealed blocks changed what the session summary counts."""

    @abstractmethod
    def resume_retained_history(self) -> None:
        """A returning tab resumes the history it kept while parked."""

    def refresh_native_projection(self) -> None:
        """A returning tab republishes its bound owner's facts beside the history."""
        self.agent_binding.refresh_projection(self)
