"""A channel or direct conversation's wire messages as pages of line-drawn fragments.

Core answers each page (`MessagePage`). This module turns one into what the
line history draws and pages by: fragments, and the cuts a page lies between.
Nothing here imports a terminal library.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from agent_comms import HistoricalMessage
from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage
from agent_comms.messages import Message
from agent_comms.presentation import WireRevision

from toad.conversation_kind import ConversationKind
from toad.line_blocks import Body, Gap, LineBlock, MutedRole, Summary
from toad.message_rows import MessageRow, WireMessageStyle
from toad.transcript_preparation import (
    PageRequest, PreparedTranscriptPage, TranscriptPageBuffer, TranscriptPageWork,
)
from toad.widgets.message_filter import MessageCategory, OtherCategory
from toad.widgets.transcript_fragments import BusMessageFragment, MessageShown, TranscriptFragment
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

    def text_rows(self, lines: Lines, theme) -> range:
        """The rows of `lines` that draw the message's own text: seeing one is reading it."""
        from toad.widgets.transcript_lines import PlainRowCount

        # Captions, summaries and unformatted text take the same rows styled or plain.
        prepared = self.plain_lines(lines.width, theme).preparation.prepared_blocks
        trailing = len(self.trailing(self.shown))
        count = PlainRowCount(lines.width, theme)
        return range(count.height(prepared[:len(self.leading)]),
                     lines.height - count.height(prepared[-trailing:] if trailing else ()))


class MembershipFragment(WireFragment):
    """Someone joined or left: one muted line."""

    def text(self, shown):
        return (Body("— " + self.message.body, role=MutedRole, markdown=False),)


@dataclass(kw_only=True)
class MessageFragment(BusMessageFragment, WireFragment):
    """A sent message: its header, text and the state of its notifications."""

    outgoing: bool

    @property
    def notification_references(self):
        return self.message.notification_references()

    @cached_property
    def row(self) -> MessageRow:
        return MessageRow.of(self.message, outgoing=self.outgoing)

    @property
    def leading(self):
        message = self.message
        if not isinstance(message, HistoricalMessage):
            return super().leading
        return (Gap(), Summary.titled(f"History · {message.source.original_root} · @{message.sender} "
                               f"{message.sender_incarnation.birth_description}"), self.row.header)

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
        shown = MessageShown(style=self.style)
        fragments = tuple(
            WireFragment.of(message, shown=shown, evidence=evidence,
                            **({} if message.membership is not None
                               else {"outgoing": message.sender == self.me}))
            for message in page.messages)
        wire = WirePage(
            page.messages,
            BeforeMessage(page.oldest_cursor) if page.messages else None,
            AfterMessage(page.newest_cursor) if page.has_newer and page.messages else through,
            page.has_older and bool(page.messages), page.has_newer and bool(page.messages), page,
        )
        return PreparedTranscriptPage.measured(wire, fragments)

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
