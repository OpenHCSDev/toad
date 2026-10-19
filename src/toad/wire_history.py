"""A channel or direct conversation's wire messages as pages of line-drawn fragments.

Core answers each page (`MessagePage`). This module turns one into what the
line history draws and pages by: fragments, and the cuts a page lies between.
Nothing here imports a terminal library.
"""

from __future__ import annotations

import asyncio
from abc import ABC
from dataclasses import dataclass, field, replace
from functools import cached_property, partial, singledispatch
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage
from agent_comms.transcript_events import IncomingTranscript
from agent_comms.page_traversal import LiveCursor, NewerTraversal, OlderTraversal, PageCursor
from agent_comms.messages import Message, ConversationRole, NoticeRole, Membership
from agent_comms.historical_views import ConversationHistoryView, ConversationRevision

from toad.conversation_kind import ConversationKind
from toad.line_blocks import Body, Gap, LineBlock, MutedRole, Summary
from toad.message_rows import MessageRow, WireMessageStyle
from toad.transcript_preparation import (
    PageRequest, PreparedTranscriptPage, SavedHistory, TranscriptPageWork,
)
from toad.widgets.message_filter import MessageCategory, OtherCategory
from toad.widgets.message_notifications import PaintedRead, ReadWork
from toad.widgets.transcript_fragments import BusMessageFragment, MessageShown, TranscriptFragment

if TYPE_CHECKING:
    from agent_comms.read_basis import NamedViewer
    from toad.widgets.transcript_lines import Lines


@dataclass(frozen=True)
class WireCut(ABC):
    """A place between two wire messages, where a page begins or ends."""

    cursor: PageCursor

    def older(self) -> OlderTraversal:
        return self.cursor.older()

    def newer(self) -> NewerTraversal:
        return self.cursor.newer()

    # Whether a page read from this cut depends on how far the bus has grown.
    bounded: ClassVar[bool]
    # Whether a page read from this cut is kept for the next reader of the same page.
    kept: ClassVar[bool]


@dataclass(frozen=True)
class BeforeMessage(WireCut):
    """Just before the message Core's cursor names; earlier messages never change."""

    bounded = False
    kept = True


@dataclass(frozen=True)
class AfterMessage(WireCut):
    """Just after the message Core's cursor names."""

    bounded = True
    kept = True


@dataclass(frozen=True)
class AfterSequence(AfterMessage):
    """After everything the bus held up to a sequence number, whoever it was for.

    The end of the conversation is read from here: each read is a new answer.
    """

    cursor: LiveCursor
    kept = False

    def older(self) -> OlderTraversal:
        return OlderTraversal(self.cursor.sequence + 1)


@dataclass(frozen=True)
class NothingRead(AfterSequence):
    """Where the placeholder drawn before the first read ends.

    It reads like the start of the bus but never equals a cursor Core answered,
    so even an empty bus is read once instead of taken as already drawn.
    """

    cursor: LiveCursor = field(default_factory=lambda: LiveCursor(0))


@dataclass(frozen=True)
class WirePage:
    """One page as the line history pages it; `source` is Core's page with its read evidence."""

    events: tuple[Message, ...]
    before: BeforeMessage | None
    after: AfterMessage
    has_older: bool
    has_newer: bool
    source: MessagePage | None

    @classmethod
    def unread(cls) -> WirePage:
        """What is drawn before the first read: nothing, ending before any answer."""
        return cls((), None, NothingRead(), False, False, None)

    @property
    def undrawn(self) -> bool:
        return self.source is None

    def accepts(self, page: MessagePage, view: type[ConversationHistoryView]) -> bool:
        """An initial placeholder accepts its first scope; Core compares actual pages."""
        source = self.source
        return source is None or view.same_display(page, source)

    def advanced(self, interval: WirePage, *, older: bool) -> WirePage:
        """An empty interval advances its cut and establishes the first Core page.

        Existing fragments retain their original page evidence; a placeholder
        must adopt the actual empty Core page rather than remain unobserved.
        """
        source = interval.source if self.undrawn else self.source
        return (replace(self, before=interval.before, has_older=interval.has_older, source=source)
                if older else replace(self, after=interval.after, has_newer=interval.has_newer,
                                      source=source))


class PreparedWirePage(PreparedTranscriptPage):
    """Wire intervals preserve Core's original display page when advanced empty."""

    def advance_empty(self, prepared: PreparedTranscriptPage, older: bool) -> None:
        self.page = self.page.advanced(prepared.page, older=older)


@dataclass(kw_only=True)
class WireFragment(TranscriptFragment):
    """One wire message drawn as lines.

    `evidence` is Core's page whose display evidence can mark this message
    read; it is None when the page carried none and once the mark is written.
    """

    shown: MessageShown
    evidence: MessagePage | None
    checks_notifications: ClassVar[bool] = False

    def _unhandled_message(message, **fields):
        raise TypeError(f"No fragment declared for {type(message.role).__name__}")

    _roles = singledispatch(_unhandled_message)

    def __init_subclass__(cls, *, roles=(), **kwargs):
        super().__init_subclass__(**kwargs)
        for role in roles:
            WireFragment._roles.register(role, cls.from_message)

    @classmethod
    def of(cls, message: Message, *, reader: str, **fields) -> WireFragment:
        return cls._roles.dispatch(type(message.role))(message, reader=reader, **fields)

    @classmethod
    def from_message(cls, message, *, reader, **fields):
        return cls((IncomingTranscript(message=message, reader=reader),), **fields)

    @property
    def message(self) -> Message:
        return self.events[0].message

    @cached_property
    def categories(self) -> frozenset[type[MessageCategory]]:
        return frozenset({OtherCategory})

    @property
    def timestamp(self) -> float | None:
        return self.message.timestamp

    @property
    def clipboard_text(self) -> str:
        return self.message.body

    @property
    def leading(self) -> tuple[LineBlock, ...]:
        """Blocks above the message's own text."""
        return ()

    def trailing(self, shown: MessageShown) -> tuple[LineBlock, ...]:
        """Blocks below the message's own text."""
        return ()

    def text(self, shown: MessageShown) -> tuple[LineBlock, ...]:
        """The message's own text."""
        raise NotImplementedError

    def blocks(self, shown):
        return (*self.leading, *self.text(shown), *self.trailing(shown))

    def text_rows(self, lines: Lines) -> range:
        """Read visibility uses the same block snapshots that draw this viewport."""
        prepared = lines.prepared_blocks
        trailing = len(self.trailing(self.shown))
        return range(sum(block.height for block in prepared[:len(self.leading)]),
                     lines.height - sum(block.height for block in prepared[-trailing:] if trailing))


class MembershipFragment(WireFragment, roles=(Membership,)):
    """Someone joined or left: one muted line."""

    def text(self, shown):
        return (Body("— " + self.message.body, role=MutedRole),)


@dataclass(kw_only=True)
class MessageFragment(BusMessageFragment, WireFragment, roles=(ConversationRole, NoticeRole)):
    """A sent message: its header, text and the state of its notifications."""

    @classmethod
    def from_message(cls, message, *, reader, **fields):
        return cls((IncomingTranscript(message=message, reader=reader),),
                   text_part=message.body, row=MessageRow(message, reader), **fields)

    @property
    def notification_references(self):
        return self.message.role.notification_references(self.message)

    @property
    def leading(self):
        message = self.message
        source = message.history_source
        if source is None:
            return super().leading
        return (Gap(), Summary.titled(f"History · {source.original_root} · @{message.sender} "
                               f"created {message.sender_created_at}"), self.row.header)

@dataclass(frozen=True, eq=False)
class WireSource:
    """One conversation as one viewer reads it from Core, and how its messages are styled.

    A page read to the newest messages is short so that it is drawn at once;
    every other read takes a whole transport page.
    """

    comms: Comms
    kind: type[ConversationKind]
    target: str
    project: Path
    me: str
    style: WireMessageStyle
    tail_limit: int = 8
    page_limit: int = 40
    max_bytes: int = 256 * 1024

    @property
    def viewer(self) -> NamedViewer:
        return self.comms.views.display_viewer(str(self.project))

    def observe(self, seen: ConversationRevision | None) -> WireObservation | None:
        """What changed since `seen`, or None when the stores are as they were."""
        revision = self.kind.history_view.revision(
            self.comms.views, self.target, worktree=str(self.project))
        if revision == seen:
            return None
        high = AfterSequence(LiveCursor(self.comms.views.latest_sequence()))
        # Core's display view owns which stores can replace this reading.
        # Notification/read/activity writes do not require a page to learn that.
        replaced = seen is None or revision.display_changed_since(seen)
        return WireObservation(revision, high, replaced)

    def read(self, request: PageRequest[WireCut], through: AfterSequence) -> PreparedTranscriptPage:
        """Read the page a request names, never past `through`, as fragments to draw."""
        page = request.end.wire_page(self, request.cursor, through)
        shown = MessageShown(style=self.style)
        fragments = tuple(
            WireFragment.of(message, shown=shown, evidence=page.evidence_for(message), reader=self.me)
            for message in page.messages)
        wire = WirePage(
            page.messages,
            BeforeMessage(page.messages[0].view_cursor) if page.messages else None,
            AfterMessage(page.messages[-1].view_cursor) if page.has_newer and page.messages else through,
            page.has_older and bool(page.messages), page.has_newer and bool(page.messages), page,
        )
        return PreparedWirePage.measured(wire, fragments)

    def restyled(self, style: WireMessageStyle) -> WireSource:
        return replace(self, style=style)


@dataclass(frozen=True)
class WireObservation:
    revision: ConversationRevision
    through: AfterSequence
    replaced: bool


@dataclass(frozen=True)
class WirePageWork(TranscriptPageWork[WireCut]):
    """Read one wire page off the UI thread; `loader` is the WireSource."""

    @property
    def retain_result(self) -> bool:
        return self.request.cursor.kept

    async def execute(self, runtime, key):
        import asyncio

        prepared = await runtime.run_thread(self.loader.read, self.request, self.through)
        if self.scope.closed:
            raise asyncio.CancelledError
        return await runtime.run_thread(self.finish_result, key, prepared)


class WirePageBuffer(SavedHistory):
    """The line history's page reader over a wire source."""

    work = WirePageWork

    def uses_observation(self, observation) -> bool:
        return observation.uses(self.loader.comms)

    async def route_is_current(self) -> bool:
        from agent_comms.route_selection import root_is_current

        return not self.closed and await self.runtime.run_thread(root_is_current, self.loader.comms.root)

    def status_thread(self, access):
        from toad.widgets.observed_thread_activity import NoStatusThread, StatusThread

        name = self.loader.kind.historical_thread(self.loader.target)
        return (NoStatusThread() if name is None else
                StatusThread.for_root(self.loader.comms.root, name, access))

    def command_context(self, view):
        from toad.target_commands import TargetContext
        from toad.screens.session_view import SessionView

        return TargetContext(view.app, self.loader.comms, self.loader.target, self.loader.me,
                             self.loader.project, view.query_ancestor(SessionView).id)

    async def submit_input(self, view, event) -> None:
        target = self.loader.target
        current = lambda: (view.is_attached and self is view.message_history.page_source
                           and target == view.target)
        await view.submit_comms_message(
            self.loader.comms.root, self.loader.kind, target, event.body, current,
            partial(view._show_sent, body=event.body))

    def schedule_refresh(self, view):
        history = view.message_history
        history.notification_view.check_notifications()
        return history.schedule_source_work(view._refresh_source)

    def painted_read(self, history) -> PaintedRead:
        return ReadWork(history._mark_read(history.source_snapshot()))

    async def change_style(self, history) -> None:
        if not history.can_draw_on_screen:
            return
        style = self.loader.style.next()
        history.open(self.loader.restyled(style))
        await history._show([(fragment, replace(fragment.shown, style=style))
                             for fragment in history.fragments])
        history.window.scroll_end(animate=False)

    async def read_revision(self):
        return await self.runtime.run_thread(self.loader.comms.views.revision)

    async def observe_changes(self, revision):
        return await self.runtime.run_thread(self.loader.observe, revision)

    def accepts_page(self, current, incoming) -> bool:
        return current.accepts(incoming.source, self.loader.kind.history_view)

    def seen_page(self, history, seen):
        return self.loader.kind.seen_page(history, seen)

    async def mark_page(self, page) -> None:
        from agent_comms.route_selection import implicit_root, run_selected_write

        comms = self.loader.comms
        await asyncio.to_thread(
            run_selected_write, comms.root, comms.views.mark_page_read, page,
            worktree=str(self.loader.project), implicit=implicit_root())

    async def read_only(self) -> bool:
        return await self.runtime.run_thread(
            self.loader.kind.read_only, self.loader.comms, self.loader.target)

    async def update_mentions(self, view) -> None:
        await self.loader.kind.update_mentions(view, self.loader.comms)

    async def status_text(self, *, read_only):
        return await self.loader.kind.status_text(self.loader.comms, self.loader.target,
                                                  read_only=read_only)

    def accepts(self, loader, through) -> bool:
        # Earlier wire cuts stay valid while the bus grows.
        return self.loader is loader
