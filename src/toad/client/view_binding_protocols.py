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


if TYPE_CHECKING:
    from agent_comms.execution.transcript_sources import DraftRow, TranscriptCursor
    from agent_comms.transcript.transcript_drafts import NoDraft
    from agent_comms.transcript.transcripts import TranscriptReadIdentity
    from toad.client.prepared_pages import PreparedPageSource, PreparedTranscriptPage
    from toad.client.transcript_history_contract import TranscriptHistoryContract
    from toad.core.events import ThreadRowsChanged
    from toad.session_scope import SessionScope
    from toad.transcript_publication import PublicationWork


class BoundViewHost:
    """What `BoundView` requires of its host view. A plain mixin, like the other shared
    view bases: each toolkit's widget metaclass (`AbstractHooksMeta`) refuses a view class
    that leaves one of these abstract."""

    MAX_LIVE_BLOCKS: ClassVar[int]
    """How many live blocks may stand before a refresh commits them into history. A view
    that draws no live blocks sets 1: every refresh commits."""

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
    def transcript_history(self) -> "TranscriptHistoryContract":
        """The single transcript-page-producing child `BoundView` drives."""

    @abstractmethod
    def query_ancestor(self, kind: type["SessionScope"]) -> "SessionScope":
        """The enclosing `SessionScope`; `LookupError` when the view has none."""

    @property
    @abstractmethod
    def ancestors(self) -> Iterable[object]:
        """Every ancestor up the tree; `source in view.ancestors` asks whether a scope
        still contains the view."""

    # ---- the thread ----

    @abstractmethod
    def thread_observed(self, event: "ThreadRowsChanged") -> None:
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
    def show_draft(self, draft: "DraftRow | NoDraft", identity: "TranscriptReadIdentity") -> None:
        """Draw the thread's in-progress CLI draft after the history, or clear it."""

    @abstractmethod
    def empty_history(self) -> "TranscriptHistoryContract":
        """A new history with no source pages yet, for a replaced source."""

    @abstractmethod
    def later_history(
        self, page: "PreparedTranscriptPage", source: "PreparedPageSource", conversation_order: int
    ) -> "TranscriptHistoryContract":
        """A history continuing after an entry placed into this one."""

    @abstractmethod
    def mount_history(
        self, history: "TranscriptHistoryContract", *, before: "TranscriptHistoryContract | None" = None
    ) -> Awaitable[None]:
        """Draw this history among the blocks (after them, or before `before`)."""

    @abstractmethod
    def remove_history(self, history: "TranscriptHistoryContract") -> Awaitable[None]:
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
    def start_publication(self, task: Callable[[], Awaitable[object]], *, exclusive: bool) -> "PublicationWork":
        """Run a publication on the native loop; an exclusive one supersedes its kind."""

    @abstractmethod
    def cancel_publications(self) -> tuple["PublicationWork", ...]:
        """Cancel this view's running publications and return them to join."""

    @abstractmethod
    def current_publication(self) -> object:
        """The running publication's handle, as `PublicationWork.runs` compares it."""

    # ---- what a publication tells the view ----

    @abstractmethod
    def history_painted(self) -> None:
        """A publication painted the history: retire loading paint, settle submissions."""

    @abstractmethod
    def refresh_session_summary(self) -> None:
        """Retired or revealed blocks changed what the session summary counts."""

    @abstractmethod
    def resume_retained_history(self) -> None:
        """A returning tab resumes the history it kept while parked."""

    def refresh_native_projection(self) -> None:
        """A returning tab republishes its bound owner's facts beside the history."""
        self.agent_binding.refresh_projection(self)
