"""A message on the bus as rows draw it.

A channel, a thread's saved history and a message being sent all draw one
through this: a header rule carrying "sender → destination · time", whose
names open the thread or channel they name, then the text in one of two
styles. The cursor's menu on a message opens the same names from the
keyboard. Nothing here imports a terminal library.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
import time
from typing import ClassVar

from agent_comms.channel_targets import CommandTarget, ChannelTarget, ThreadTarget
from metaclass_registry.mro_dispatch import MroDispatch, handles
from agent_comms.declared_family import DeclaredFamily
from agent_comms.messages import Message
from agent_comms.routing import MessageRoute

from toad.inline_spans import inline_spans
from toad.menus import MenuItem
from toad.line_blocks import (
    MarkdownBody, Divider, IncomingRole, LineBlock, LineLink, LineRole, NameRole,
    OpenHistoricalTarget, OpenTarget, OutgoingRole, Span, Spans,
)


class MessageClock:
    """When a displayed message happened, independent of its native divider."""

    fresh: ClassVar[bool] = False
    timestamp: float | None

    def display(self) -> tuple[str, str | None]:
        timestamp = self.timestamp
        if timestamp is None:
            return "time unknown", None
        local = time.localtime(timestamp)
        return time.strftime("%Y-%m-%d %H:%M:%S", local), time.strftime("%Y-%m-%d %H:%M:%S %Z", local)

    @classmethod
    def recorded(cls, timestamp: float | None) -> MessageClock:
        return UnknownMessageClock() if timestamp is None else RecordedMessageClock(timestamp)


class LiveMessageClock(MessageClock):
    fresh = True

    @property
    def timestamp(self) -> float:
        return time.time()


@dataclass(frozen=True)
class RecordedMessageClock(MessageClock):
    timestamp: float


class UnknownMessageClock(MessageClock):
    timestamp = None


@dataclass(frozen=True)
class MessageRow(MroDispatch):
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
    def history(self) -> str | None:
        source = self.message.history_source
        return source.key if source is not None else None

    @property
    def role(self) -> type[LineRole]:
        return OutgoingRole if self.outgoing else IncomingRole

    def name(self, target: str, role: type[LineRole] = NameRole) -> Span:
        """A thread or channel name that opens what it names."""
        identity = CommandTarget.named(target)
        return Span(target, role, next(self.handlers_for(identity))(identity))

    @handles(ThreadTarget)
    def thread_link(self, target: ThreadTarget) -> LineLink:
        return (OpenHistoricalTarget(target.name, self.history)
                if self.history is not None else OpenTarget(target.name))

    @handles(ChannelTarget)
    def channel_link(self, target: ChannelTarget) -> LineLink:
        return OpenTarget(target.name)

    @property
    def sender(self) -> LineLink:
        """What opens the thread that sent the message."""
        return self.name(self.route.sender).link

    @property
    def destination(self) -> LineLink:
        """What opens the first thread or channel the message was sent to."""
        return self.name(self.route.targets[0]).link

    @property
    def menu(self) -> tuple[MenuItem, ...]:
        """What the cursor's menu offers on this message, wherever it is drawn."""
        return (MenuItem("Open [u]s[/u]ender", "block.open_sender", "s"),
                *(MenuItem("Open [u]d[/u]estination", "block.open_destination", "d"),) * bool(self.route.targets))

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
        return Divider(spans, self.role, self.timestamp)


@dataclass(frozen=True)
class WireBody(LineBlock):
    """Where a message came from stays with the message, not with a theme or paragraph."""

    row: MessageRow
    text: str
    bar = None

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
