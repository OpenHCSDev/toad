"""A message on the bus as rows draw it.

A channel, a thread's saved history and a message being sent all draw one
through this: a header rule carrying "sender → destination · time", whose
names open the thread or channel they name, then the text in one of two
styles. Nothing here imports a terminal library.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

from agent_comms import HistoricalMessage
from agent_comms.declared_family import DeclaredFamily
from agent_comms.mentions import ThreadMention
from agent_comms.messages import Message
from agent_comms.routing import MessageRoute
from agent_comms.transcript_events import IncomingTranscript, SentTranscript

from toad.inline_spans import inline_spans
from toad.line_blocks import (
    Body, Divider, IncomingRole, LineBlock, LineLink, LineRole, NameRole, OpenHistoricalTarget,
    OpenTarget, OutgoingRole, Span, Spans,
)


@dataclass(frozen=True)
class MessageRow:
    """One message: who sent it to whom, when, its text, and whether the reader's thread sent it."""

    route: MessageRoute
    text: str
    timestamp: float | None
    outgoing: bool
    mentions: tuple[ThreadMention, ...] = ()
    # The attached history source the message was read from: its threads open as that source recorded them.
    history: str | None = None

    @classmethod
    def of(cls, message: Message, *, outgoing: bool) -> MessageRow:
        return cls(MessageRoute(message.sender, (message.target,)), message.body, message.timestamp,
                   outgoing, message.mentions,
                   message.source.key if isinstance(message, HistoricalMessage) else None)

    @classmethod
    def incoming(cls, event: IncomingTranscript) -> MessageRow:
        return cls(event.route, event.text, event.timestamp, outgoing=False)

    @classmethod
    def sent(cls, event: SentTranscript) -> MessageRow:
        return cls(event.routing.reply, event.text, event.timestamp, outgoing=True)

    @property
    def role(self) -> type[LineRole]:
        return OutgoingRole if self.outgoing else IncomingRole

    def name(self, target: str) -> Span:
        """A thread or channel name that opens what it names."""
        link: LineLink = (OpenHistoricalTarget(target, self.history)
                          if self.history is not None and not target.startswith("#")
                          else OpenTarget(target))
        return Span(target, NameRole, link)

    @property
    def route_text(self) -> str:
        targets = ", ".join(self.route.targets)
        return f"{self.route.sender} → {targets}" if targets else self.route.sender

    @property
    def header(self) -> Divider:
        spans = [self.name(self.route.sender)]
        for index, target in enumerate(self.route.targets):
            spans += [Span(", " if index else " → "), self.name(target)]
        return Divider(tuple(spans), self.role, self.timestamp)


class WireMessageStyle(DeclaredFamily, affix="MessageStyle"):
    """How a message's own text is laid out under its header."""

    @abstractmethod
    def body(self, row: MessageRow) -> tuple[LineBlock, ...]: ...

    @abstractmethod
    def next(self) -> WireMessageStyle: ...

    @abstractmethod
    def clipboard(self, row: MessageRow) -> str:
        """What copying a message drawn in this style gives."""


class IrcMessageStyle(WireMessageStyle):
    """Inline-formatted text as one wrapped paragraph."""

    def body(self, row):
        return (Spans(inline_spans(row.text, row.mentions)),)

    def next(self):
        return MarkdownMessageStyle()

    def clipboard(self, row):
        return f"{row.route_text}: {row.text}"


class MarkdownMessageStyle(WireMessageStyle):
    """The text as Markdown beside a bar, then who it mentions."""

    def body(self, row):
        blocks: list[LineBlock] = [Body(row.text, bar=row.role)]
        if row.mentions:
            names = dict.fromkeys(mention.thread for mention in row.mentions)
            mentioned = [Span("Mentioned: ")]
            for index, target in enumerate(names):
                mentioned += [Span(", ")] * bool(index) + [row.name(target)]
            blocks.append(Spans(tuple(mentioned)))
        return tuple(blocks)

    def next(self):
        return IrcMessageStyle()

    def clipboard(self, row):
        return row.text
