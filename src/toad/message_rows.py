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
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.storage.recorded_time import EventTime, RecordedEventTime, UnrecordedEventTime
from metaclass_registry.mro_dispatch import handles

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
    cells for Textual, pixels for Qt. The frontend measures; this owner decides how a title
    wraps and how much rule each line carries, so every frontend draws the same lines."""

    @abstractmethod
    def measure(self, text: str) -> float:
        """The width this text takes in the frontend's measure."""

    @property
    @abstractmethod
    def capacity(self) -> float:
        """The widest title one divider line may carry."""

    @abstractmethod
    def fits(self, spans: tuple[Span, ...]) -> bool:
        """Whether a title and its time share one line."""

    @abstractmethod
    def rules(self, spans: tuple[Span, ...]) -> tuple[int, int]:
        """Rule characters before and after one line's title."""

    def wrap(self, spans: tuple[Span, ...]) -> tuple[tuple[Span, ...], ...]:
        """The lines a title wraps into at this room's capacity, word by word, each span
        keeping its role and link; a word wider than a line breaks between characters."""
        lines: list[tuple[Span, ...]] = []
        line: list[Span] = []
        used = 0.0
        for span in spans:
            for word in _words(span.text):
                for piece in self._pieces(word):
                    if line and used + self.measure(piece.rstrip()) > self.capacity:
                        lines.append(_trimmed(line))
                        line, used, piece = [], 0.0, piece.lstrip()
                    if piece:
                        line.append(replace(span, text=piece))
                        used += self.measure(piece)
        if line or not lines:
            lines.append(_trimmed(line))
        return tuple(lines)

    def _pieces(self, word: str) -> tuple[str, ...]:
        if self.measure(word.rstrip()) <= self.capacity:
            return (word,)
        pieces, current = [], ""
        for character in word:
            if current and self.measure(current + character) > self.capacity:
                pieces.append(current)
                current = ""
            current += character
        return (*pieces, current)


def _words(text: str) -> tuple[str, ...]:
    """Each word with the spaces that follow it, so joining them gives the text back."""
    return tuple(re.findall(r"\S+\s*|\s+", text))


def _trimmed(line: list[Span]) -> tuple[Span, ...]:
    if line:
        line[-1] = replace(line[-1], text=line[-1].text.rstrip())
    return tuple(line)


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


@dataclass(frozen=True)
class DividerLine:
    """One drawn line of a divider: its title and the rule on each side of it."""

    spans: tuple[Span, ...]
    before: int
    after: int


class DrawsDividers(ABC):
    """Draws a divider the one way every frontend does: the title and time grouped by
    DIVIDER_TIME, each group wrapped to the room, and every line ruled on both sides. A
    frontend says only how a ruled line looks and how its lines join."""

    @abstractmethod
    def divider_room(self) -> LineRoom: ...

    @abstractmethod
    def ruled_line(self, line: DividerLine, block: Divider): ...

    @abstractmethod
    def joined_divider(self, lines: tuple): ...

    @handles(Divider)
    def divider(self, block: Divider):
        room = self.divider_room()
        return self.joined_divider(tuple(
            self.ruled_line(DividerLine(line, *room.rules(line)), block)
            for group in DIVIDER_TIME.project_value(block.timestamp, block.spans, room)
            for line in room.wrap(group)))


class ThreadLink(MroProjection[LineLink]):
    """A thread name opens the live thread, or the thread as the history that recorded the message."""

    @handles(NoHistorySource)
    def live(self, source: NoHistorySource, name: str) -> LineLink:
        return OpenTarget(name)

    @handles(HistorySource)
    def recorded(self, source: HistorySource, name: str) -> LineLink:
        return OpenHistoricalTarget(name, source.key)


THREAD_LINK = ThreadLink()


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
    def sender(self) -> LineLink:
        """What opens the thread that sent the message."""
        return self.name(self.route.sender).link

    @property
    def route_text(self) -> str:
        return self.header.label

    @property
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


class InlineWireBody(WireBody):
    def prepare(self, context):
        return Spans(inline_spans(self.text, context))


class MarkdownWireBody(WireBody):
    @property
    def bar(self):
        return self.row.role

    def prepare(self, context):
        return MarkdownBody(self.text, bar=self.bar)


class WireMessageStyle(DeclaredFamily, affix="MessageStyle"):
    """How a message's own text is laid out under its header."""

    def body(self, row: MessageRow, text: str) -> tuple[LineBlock, ...]:
        return (self.body_type(row, text),)

    @abstractmethod
    def next(self) -> WireMessageStyle: ...

    @abstractmethod
    def clipboard(self, row: MessageRow) -> str:
        """What copying a message drawn in this style gives."""


class IrcMessageStyle(WireMessageStyle):
    """Inline-formatted text as one wrapped paragraph."""

    body_type = InlineWireBody

    def next(self):
        return MarkdownMessageStyle()

    def clipboard(self, row):
        return f"{row.route_text}: {row.text}"


class MarkdownMessageStyle(WireMessageStyle):
    """The same inline links, laid out as Markdown beside a bar."""

    body_type = MarkdownWireBody

    def next(self):
        return IrcMessageStyle()

    def clipboard(self, row):
        return row.text
