"""A message on the bus as rows draw it.

A channel, a thread's saved history and a message being sent all draw one
through this: a header rule carrying "sender → destination · time", whose
names open the thread or channel they name, then the text in one of two
styles. The cursor's menu on a message opens the same names from the
keyboard. Nothing here imports a terminal library.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from functools import cached_property
from typing import ClassVar

from agent_comms.messaging.display_references import NoHistorySource
from agent_comms.messaging.channel_targets import (
    ChannelTarget,
    CommandTarget,
    ThreadTarget,
)
from agent_comms.messaging.historical_views import HistorySource
from agent_comms.messaging.messages import Message
from agent_comms.messaging.routing import MessageRoute
from agent_comms.nominal.declared_choice import DeclaredChoice, TitledChoice
from agent_comms.storage.recorded_time import EventTime, RecordedEventTime, UnrecordedEventTime
from metaclass_registry.mro_dispatch import handles
from rich.cells import cell_len

from toad.client.message_file_links import FileReader
from toad.client.structured_context import has_structured_tags, parse_structured_text
from toad.core.projection import MroProjection
from toad.inline_spans import inline_spans
from toad.client.line_blocks import (
    Divider,
    IncomingRole,
    LineBlock,
    LineLink,
    LineRole,
    MarkdownBody,
    NameRole,
    NoBar,
    OpenHistoricalTarget,
    OpenTarget,
    OutgoingRole,
    Span,
    Spans,
)


class MessageClock:
    """When a displayed message happened, independent of its native divider."""

    fresh: ClassVar[bool] = False
    timestamp: float

    @property
    def event_time(self) -> EventTime:
        """The time a divider records for this message."""
        return EventTime.capture(self.timestamp)

    def display(self) -> tuple[str, str]:
        """The time as drawn, and the time with its zone for a tooltip."""
        local = time.localtime(self.timestamp)
        return time.strftime("%Y-%m-%d %H:%M:%S", local), time.strftime("%Y-%m-%d %H:%M:%S %Z", local)


class LiveMessageClock(MessageClock):
    fresh = True

    @property
    def timestamp(self) -> float:
        return time.time()


@dataclass(frozen=True)
class RecordedMessageClock(MessageClock):
    timestamp: float


class LineRoom(ABC):
    """How much of a divider's title one line holds, in its frontend's own measure: terminal
    cells for Textual, pixels for Qt."""

    @abstractmethod
    def fits(self, spans: tuple[Span, ...]) -> bool: ...

    def wrapped(self, spans: tuple[Span, ...]) -> tuple[tuple[Span, ...], ...]:
        """The title as rows that fit, broken after a space, as a terminal wraps a divider's
        title; each piece keeps its span's role and link, and a word too long stands alone."""
        rows: list[tuple[Span, ...]] = []
        row: tuple[Span, ...] = ()
        for span in spans:
            for word in re.findall(r"\S*\s*", span.text)[:-1] or [span.text]:
                piece = replace(span, text=word)
                if row and not self.fits((*row, piece)):
                    rows.append(row)
                    row = ()
                row = (*row, piece)
        return (*rows, row)


@dataclass(frozen=True)
class CellRoom(LineRoom):
    """A divider line measured in terminal cells, shared by every monospace frontend."""

    width: int

    def fits(self, spans: tuple[Span, ...]) -> bool:
        return sum(cell_len(span.text) for span in spans) <= max(1, self.width - 8)


class DividerTime(MroProjection[tuple[tuple[Span, ...], ...]]):
    """A recorded divider shows its time beside the title, or below it when they do not fit
    on one line; an unrecorded one shows none. Each group is one line of the divider."""

    @handles(RecordedEventTime)
    def recorded(self, time: RecordedEventTime, spans: tuple[Span, ...], room: LineRoom):
        shown = RecordedMessageClock(time.at).display()[0]
        timed = (*spans, Span(f" · {shown}"))
        return (timed,) if room.fits(timed) else (spans, (Span(shown),))

    @handles(UnrecordedEventTime)
    def unrecorded(self, time: UnrecordedEventTime, spans: tuple[Span, ...], room: LineRoom):
        return (spans,)


DIVIDER_TIME = DividerTime()


class ThreadLink(MroProjection[LineLink]):
    """A thread name opens the live thread, or the thread as the history that recorded the message."""

    @handles(NoHistorySource)
    def live(self, source: NoHistorySource, name: str) -> LineLink:
        return OpenTarget(name)

    @handles(HistorySource)
    def recorded(self, source: HistorySource, name: str) -> LineLink:
        return OpenHistoricalTarget(name, source.key)


THREAD_LINK = ThreadLink()


class MessageFileReader(MroProjection[FileReader]):
    """Whose read a message's files are, from where it was sent: a channel message is read in
    its channel; a direct message in its own DM, as its sender. The reader is not always a
    participant: #any shows DMs between two other threads, and naming the reader's DM with
    the sender there was refused, failing the whole page (2026-11-18)."""

    @handles(ChannelTarget)
    def channel(self, target: ChannelTarget, row: MessageRow) -> FileReader:
        return FileReader(target.name, row.reader)

    @handles(ThreadTarget)
    def direct(self, target: ThreadTarget, row: MessageRow) -> FileReader:
        return FileReader(target.name, row.message.sender)


MESSAGE_FILE_READER = MessageFileReader()


@dataclass(frozen=True)
class MessageRow(MroProjection[LineLink]):
    """One message: who sent it to whom, when, its text, and whether the reader's thread sent it."""

    message: Message
    reader: str

    @property
    def route(self) -> MessageRoute:
        return MessageRoute(self.message.sender, (self.message.target,))

    @property
    def text(self) -> str:
        return self.message.body

    @property
    def timestamp(self) -> float:
        return self.message.timestamp

    @property
    def outgoing(self) -> bool:
        return self.message.sender == self.reader

    @property
    def role(self) -> type[LineRole]:
        return OutgoingRole if self.outgoing else IncomingRole

    def name(self, target: str, role: type[LineRole] = NameRole) -> Span:
        """A thread or channel name that opens what it names."""
        identity = CommandTarget.named(target)
        return Span(target, role, self.project_value(identity))

    @handles(ThreadTarget)
    def thread_link(self, target: ThreadTarget) -> LineLink:
        return THREAD_LINK.project_value(self.message.history_source, target.name)

    @handles(ChannelTarget)
    def channel_link(self, target: ChannelTarget) -> LineLink:
        return OpenTarget(target.name)

    @property
    def file_reader(self) -> FileReader:
        """The read this message's files are listed and fetched under."""
        return MESSAGE_FILE_READER.project_value(CommandTarget.named(self.message.target), self)

    @property
    def sender(self) -> LineLink:
        """What opens the thread that sent the message."""
        return self.name(self.route.sender).link

    @property
    def route_text(self) -> str:
        return self.header.label

    @cached_property
    def header(self) -> Divider:
        sender = (self.name(self.route.sender, self.role),)
        targets: list[Span] = []
        for index, target in enumerate(self.route.targets):
            if index:
                targets.append(Span(", "))
            targets.append(self.name(target))
        if not targets:
            spans = sender
        elif self.outgoing:
            spans = sender + (Span(" ──> ", self.role),) + tuple(targets)
        else:
            spans = tuple(targets) + (Span(" <── ", self.role),) + sender
        return Divider(spans, self.role, EventTime.capture(self.timestamp))


@dataclass(frozen=True)
class WireBody(LineBlock):
    """Where a message came from stays with the message, not with a theme or paragraph."""

    row: MessageRow
    text: str
    bar: ClassVar[type[LineRole]] = NoBar

    @property
    def selection_text(self):
        return self.text

    @abstractmethod
    def prepare(self, context) -> LineBlock: ...

    def prepared_in(self, links) -> LineBlock:
        """This body as its style lays it out, linked through the names its message's source
        knows: what every frontend paints in its place."""
        return self.prepare(links.for_source(self.row.message.history_source))


class InlineWireBody(WireBody):
    def prepare(self, context):
        return Spans(inline_spans(self.text, context))


class MarkdownWireBody(WireBody):
    @property
    def bar(self):
        return self.row.role

    def prepare(self, context):
        return MarkdownBody(self.text, bar=self.bar)


_LEADING_BLANK_LINES = re.compile(r"^(?:[ \t]*\r?\n)+")


class WireMessageStyle(DeclaredChoice, affix="MessageStyle"):
    """How a message's own text is laid out under its header: a conversation tab opens in
    the style `ConversationUiSettings.message_style` names, in every frontend."""

    def body(self, row: MessageRow, text: str) -> tuple[LineBlock, ...]:
        text = _LEADING_BLANK_LINES.sub("", text)
        if has_structured_tags(text, allow_unclosed=False):
            blocks = tuple(
                block
                for part in parse_structured_text(text, allow_unclosed=False)
                for block in part.wire_blocks(row, self.body_type)
            )
            if blocks:
                return blocks
        return (self.body_type(row, text),)

    @abstractmethod
    def next(self) -> WireMessageStyle: ...

    @abstractmethod
    def clipboard(self, row: MessageRow) -> str:
        """What copying a message drawn in this style gives."""


class IrcMessageStyle(TitledChoice, WireMessageStyle):
    """Inline-formatted text as one wrapped paragraph."""

    title = "IRC lines"

    body_type = InlineWireBody

    def next(self):
        return MarkdownMessageStyle()

    def clipboard(self, row):
        return f"{row.route_text}: {row.text}"


class MarkdownMessageStyle(TitledChoice, WireMessageStyle):
    """The same inline links, laid out as Markdown beside a bar."""

    title = "Markdown beside a bar"

    body_type = MarkdownWireBody

    def next(self):
        return IrcMessageStyle()

    def clipboard(self, row):
        return row.text
