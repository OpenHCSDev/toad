"""A channel or direct conversation's wire messages as pages of line-drawn fragments.

Core answers each page (`MessagePage`). This module turns one into what the
line history draws and pages by: fragments, and the cuts a page lies between.
Nothing here imports a terminal library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from agent_comms import HistoricalMessage
from agent_comms.comms import Comms
from agent_comms.declared_family import DeclaredFamily
from agent_comms.message_page import MessagePage
from agent_comms.messages import Message
from agent_comms.presentation import WireRevision
from agent_comms.thread_identity import ThreadRole

from toad.conversation_kind import ConversationKind
from toad.inline_spans import inline_spans
from toad.line_blocks import (
    Body, Divider, Gap, LineBlock, LineLink, MutedRole, NameRole, NoticeRole, OpenHistoricalTarget,
    OpenTarget, Span, Spans, WorkingRole,
)
from toad.menus import MenuItem
from toad.notification_status import NotificationStatus, UncheckedNotifications
from toad.transcript_preparation import (
    PageRequest, PreparedTranscriptPage, TranscriptPageBuffer, TranscriptPageWork,
)
from toad.widgets.message_filter import MessageCategory, OtherCategory
from toad.widgets.transcript_fragments import Shown, TranscriptFragment
from toad.work_preparation import WorkKey

if TYPE_CHECKING:
    from agent_comms.historical_views import HistoryCursor
    from toad.widgets.transcript_lines import Lines


class WireCut(ABC):
    """A place between two wire messages, where a page begins or ends."""

    # Whether a page read from this cut depends on how far the bus has grown.
    bounded: ClassVar[bool]
    # Whether a page read from this cut is kept for the next reader of the same page.
    kept: ClassVar[bool]


@dataclass(frozen=True)
class BeforeMessage(WireCut):
    """Just before the message Core's cursor names; earlier messages never change."""

    cursor: int | HistoryCursor
    bounded = False
    kept = True

    def older(self) -> dict:
        return {"before": self.cursor}


@dataclass(frozen=True)
class AfterMessage(WireCut):
    """Just after the message Core's cursor names."""

    cursor: int | HistoryCursor
    bounded = True
    kept = True

    def newer(self) -> dict:
        return {"after": self.cursor}


@dataclass(frozen=True)
class AfterSequence(AfterMessage):
    """After everything the bus held up to a sequence number, whoever it was for.

    The end of the conversation is read from here: each read is a new answer.
    """

    cursor: int
    kept = False

    def older(self) -> dict:
        # Core's `before` excludes the sequence it names.
        return {"before": self.cursor + 1}


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
        """What is drawn before the first read: nothing, up to sequence zero."""
        return cls((), None, AfterSequence(0), False, False, None)


class WireMessageStyle(DeclaredFamily, affix="MessageStyle"):
    """How a message's own text is laid out between its caption and its notification line."""

    @abstractmethod
    def body(self, message: Message) -> tuple[LineBlock, ...]: ...

    @abstractmethod
    def next(self) -> WireMessageStyle: ...

    @abstractmethod
    def clipboard(self, message: Message) -> str:
        """What copying a message drawn in this style gives."""

    @staticmethod
    def name(target: str, message: Message) -> Span:
        link: LineLink = (OpenHistoricalTarget(target, message.source.key)
                          if isinstance(message, HistoricalMessage) and not target.startswith("#")
                          else OpenTarget(target))
        return Span(target, NameRole, link)

    def route(self, message: Message) -> tuple[Span, ...]:
        return (self.name(message.sender, message), Span(" → ", MutedRole),
                self.name(message.target, message))


class IrcMessageStyle(WireMessageStyle):
    """Sender, destination and inline-formatted text as one wrapped paragraph."""

    def body(self, message):
        return (Spans((*self.route(message), Span(" "),
                       *inline_spans(message.body, message.mentions))),)

    def next(self):
        return MarkdownMessageStyle()

    def clipboard(self, message):
        return f"{message.sender} → {message.target}: {message.body}"


class MarkdownMessageStyle(WireMessageStyle):
    """The route on its own line, then the text as Markdown and who it mentions."""

    def body(self, message):
        blocks: list[LineBlock] = [Spans(self.route(message)), Body(message.body)]
        if message.mentions:
            names = dict.fromkeys(mention.thread for mention in message.mentions)
            mentioned = [Span("Mentioned: ")]
            for index, target in enumerate(names):
                mentioned += [Span(", ")] * bool(index) + [self.name(target, message)]
            blocks.append(Spans(tuple(mentioned)))
        return tuple(blocks)

    def next(self):
        return IrcMessageStyle()

    def clipboard(self, message):
        return message.body


@dataclass(frozen=True)
class MessageShown(Shown):
    """What a reader chose or learned about one drawn message."""

    style: WireMessageStyle
    status: NotificationStatus = field(default_factory=UncheckedNotifications)


@dataclass(kw_only=True)
class WireFragment(TranscriptFragment):
    """One wire message drawn as lines.

    `evidence` is Core's page whose display evidence can mark this message
    read; it is None when the page carried none and once the mark is written.
    """

    shown: MessageShown
    evidence: MessagePage | None
    checks_notifications: ClassVar[bool] = False

    @classmethod
    def of(cls, message: Message, **fields) -> WireFragment:
        kind = MembershipFragment if message.membership is not None else MessageFragment
        return kind((message,), **fields)

    @property
    def message(self) -> Message:
        return self.events[0]

    @cached_property
    def categories(self) -> frozenset[type[MessageCategory]]:
        return frozenset({OtherCategory})

    @cached_property
    def retained_bytes(self) -> int:
        return len(self.message.body) + 256

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
        """The rows of `lines` that draw the message's own text: seeing one is reading it."""
        from toad.widgets.transcript_lines import PlainRowCount

        # Captions, summaries and unformatted text take the same rows styled or plain.
        count = PlainRowCount(lines.width)
        return range(count.height(self.leading),
                     lines.height - count.height(self.trailing(self.shown)))


class MembershipFragment(WireFragment):
    """Someone joined or left: one muted line."""

    def text(self, shown):
        return (Body("— " + self.message.body, role=MutedRole, markdown=False),)


@dataclass(kw_only=True)
class MessageFragment(WireFragment):
    """A sent message: caption, text and the state of its notifications."""

    direction: str
    checks_notifications = True
    has_details = True
    block_menu = (MenuItem("Open [u]s[/u]ender", "block.open_sender", "s"),
                  MenuItem("Open [u]d[/u]estination", "block.open_destination", "d"))

    @property
    def clipboard_text(self):
        return self.shown.style.clipboard(self.message)

    @property
    def leading(self):
        message = self.message
        caption = (f"History · {message.source.original_root} · @{message.sender} "
                   f"created {message.sender_created_at}"
                   if isinstance(message, HistoricalMessage) else self.direction)
        return (Gap(), Divider(caption, MutedRole, message.timestamp))

    def text(self, shown):
        return shown.style.body(self.message)

    def trailing(self, shown):
        status = shown.status
        role = NoticeRole if status.unavailable else WorkingRole if status.working else MutedRole
        summary = shown.summary(status.title, role)
        if not shown.details_open:
            return (summary,)
        details = "\n".join("  " + line for line in status.details.splitlines())
        return (summary, Body(details, role=MutedRole, markdown=False))


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

    def page(self, **bounds) -> MessagePage:
        return self.kind.page(self.comms, self.target, worktree=str(self.project),
                              max_bytes=self.max_bytes, **bounds)

    def observe(self, seen: WireRevision | None, through: AfterSequence,
                identity: tuple | None) -> WireObservation | None:
        """What changed since `seen`, or None when the stores are as they were."""
        revision = self.comms.views.revision()
        if revision == seen:
            return None
        high = AfterSequence(self.comms.views.latest_sequence())
        # Without new messages the viewer, peer or channel scope may still
        # have been replaced: the pages drawn then belong to another reading.
        replaced = seen is None or (
            not high.cursor > through.cursor and identity is not None
            and revision.stores_changed_since(seen)
            and self.kind.display_identity(self.page(limit=1)) != identity)
        return WireObservation(revision, high, replaced)

    def direction(self, message: Message) -> str:
        return ("User" if message.sender_role is ThreadRole.USER else
                "Outbound" if message.sender == self.me else "Inbound")

    def read(self, request: PageRequest, through: AfterSequence) -> PreparedTranscriptPage:
        """Read the page a request names, never past `through`, as fragments to draw."""
        older = request.after is None
        cut = request.before if older else request.after
        newest = older and cut == through
        page = self.page(limit=self.tail_limit if newest else self.page_limit,
                         **(cut.older() if older else cut.newer()))
        if not older:
            # A later read owns messages that arrived after this bound.
            kept = tuple(message for message in page.messages
                         if message.view_key[0] or message.seq <= through.cursor)
            if len(kept) < len(page.messages):
                page = replace(page, messages=kept, has_newer=False)
        evidence = page if self.kind.display_identity(page) is not None else None
        shown = MessageShown(self.style)
        fragments = tuple(
            WireFragment.of(message, shown=shown, evidence=evidence,
                            **({} if message.membership is not None
                               else {"direction": self.direction(message)}))
            for message in page.messages)
        wire = WirePage(
            page.messages,
            BeforeMessage(page.oldest_cursor) if page.messages else None,
            AfterMessage(page.newest_cursor) if page.has_newer and page.messages else through,
            page.has_older and bool(page.messages), page.has_newer and bool(page.messages), page,
        )
        return PreparedTranscriptPage(wire, fragments,
                                      sum(fragment.retained_bytes for fragment in fragments))

    def restyled(self, style: WireMessageStyle) -> WireSource:
        return replace(self, style=style)


@dataclass(frozen=True)
class WireObservation:
    revision: WireRevision
    through: AfterSequence
    replaced: bool


@dataclass(frozen=True)
class WirePageWork(TranscriptPageWork):
    """Read one wire page off the UI thread; `loader` is the WireSource."""

    @property
    def work_key(self) -> WorkKey:
        cut = self.request.before or self.request.after
        return WorkKey(type(self), (self.through if cut.bounded else None, self.request), self.scope)

    @property
    def retain_result(self) -> bool:
        return (self.request.before or self.request.after).kept

    async def execute(self, runtime, key):
        import asyncio

        prepared = await runtime.run_thread(self.loader.read, self.request, self.through)
        if self.scope.closed:
            raise asyncio.CancelledError
        return await runtime.run_thread(self.finish_result, key, prepared)


class WirePageBuffer(TranscriptPageBuffer):
    """The line history's page reader over a wire source."""

    work = WirePageWork
