"""What a committed transcript fragment shows, independent of any frontend.

A fragment becomes a few line blocks. Blocks carry text and semantic roles;
a frontend maps roles to its own styles and renders the blocks. Nothing here
imports a terminal or rendering library.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass
import re

from typing import ClassVar

from agent_comms.mro_dispatch import MroDispatch, handles
from ui_theme.scheme import (
    AccentColour, ForegroundColour, MutedColour, PrimaryColour, SecondaryColour, SuccessColour,
    ThemeColour, WarningColour,
)
from agent_comms.transcript_events import (
    AgentTextTranscript, IncomingTranscript, SentTranscript, ThinkingTranscript, TranscriptEvent,
    UserTranscript,
)


class LineRole:
    """The meaning of a piece of text, and the theme colour it is drawn in."""

    colour: ClassVar[type[ThemeColour]] = ForegroundColour
    italic: ClassVar[bool] = False
    bold: ClassVar[bool] = False
    underline: ClassVar[bool] = False


class TextRole(LineRole):
    """Ordinary message text."""


class MutedRole(LineRole):
    """Secondary text: summaries, collapsed disclosures."""

    colour = MutedColour


class ThinkingRole(MutedRole):
    """The model's visible reasoning."""

    italic = True


class UserRole(LineRole):
    # The live prompt (UserInput) is drawn in the secondary colour; a committed
    # prompt keeps that colour.
    colour = SecondaryColour


class AgentRole(LineRole):
    colour = PrimaryColour


class IncomingRole(LineRole):
    """A message received from another participant."""

    colour = AccentColour


class OutgoingRole(LineRole):
    """A message sent to another participant."""

    colour = SuccessColour


class NoticeRole(LineRole):
    colour = WarningColour


class StrongRole(LineRole):
    bold = True


class EmphasisRole(LineRole):
    italic = True


class NameRole(LineRole):
    """A thread or channel name."""

    colour = AccentColour


class MentionRole(NameRole):
    bold = True


class CodeRole(LineRole):
    colour = AccentColour


class UrlRole(LineRole):
    colour = AccentColour
    underline = True


class WorkingRole(LineRole):
    """Something still in progress."""

    colour = AccentColour


class LineLink:
    """What clicking a piece of text does: the frontend runs `action` with the link's fields."""

    action: ClassVar[str]
    # Whether the text is underlined to show that it leads somewhere.
    underlined: ClassVar[bool] = True

    @property
    def click(self) -> tuple[str, tuple]:
        return self.action, astuple(self)


@dataclass(frozen=True)
class OpenTarget(LineLink):
    """Open a thread or channel."""

    action = "open_target"
    target: str


@dataclass(frozen=True)
class OpenHistoricalTarget(LineLink):
    """Open a thread as an attached history source recorded it."""

    action = "open_historical_target"
    target: str
    source: str


@dataclass(frozen=True)
class OpenUrl(LineLink):
    action = "open_url"
    url: str


@dataclass(frozen=True)
class ToggleDetails(LineLink):
    """Show or hide the details of the fragment this is drawn in."""

    action = "toggle_details"
    underlined = False


@dataclass(frozen=True)
class Span:
    """A run of text with one meaning, optionally clickable."""

    text: str
    role: type[LineRole] = TextRole
    link: LineLink | None = None


class LineBlock:
    """One visual part of a fragment."""


@dataclass(frozen=True)
class Divider(LineBlock):
    """A rule naming the speaker; the frontend formats the time."""

    label: str
    role: type[LineRole]
    timestamp: float | None = None


@dataclass(frozen=True)
class Summary(LineBlock):
    """A single collapsed line, such as a tool call or coordination context."""

    text: str
    role: type[LineRole] = MutedRole
    link: LineLink | None = None


@dataclass(frozen=True)
class Spans(LineBlock):
    """Wrapped text made of spans; line breaks in the text are kept."""

    spans: tuple[Span, ...]

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)


@dataclass(frozen=True)
class Gap(LineBlock):
    """One blank line between messages."""


@dataclass(frozen=True)
class Body(LineBlock):
    """Message text, optionally marked by a bar in another role; Markdown or plain."""

    text: str
    role: type[LineRole] = TextRole
    bar: type[LineRole] | None = None
    markdown: bool = True

    @classmethod
    def code(cls, text: str, language: str = "", **shown) -> Body:
        """Text drawn as it is written, in a language's colours when the language is known."""
        ticks = "`" * max(3, 1 + max(map(len, re.findall("`+", text)), default=0))
        return cls(f"{ticks}{language}\n{text}\n{ticks}", **shown)


class FragmentLineConsumer(MroDispatch):
    """Turn a fragment's events into line blocks, one handler per event family."""

    def __init__(self, *, show_divider: bool):
        self.show_divider = show_divider
        self.blocks: list[LineBlock] = []

    def divider(self, label: str, timestamp: float | None, role: type[LineRole]) -> None:
        if self.show_divider:
            self.blocks.append(Divider(label, role, timestamp))

    @handles(TranscriptEvent)
    def other(self, event: TranscriptEvent) -> None:
        """Events without visible text in committed history draw nothing."""

    @handles(UserTranscript)
    def user(self, event: UserTranscript) -> None:
        self.divider("User", event.timestamp, UserRole)
        self.blocks += [Body(event.text, bar=UserRole, markdown=False), Gap()]

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript) -> None:
        self.divider("Agent", event.timestamp, AgentRole)
        self.blocks += [Body(event.text), Gap()]

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript) -> None:
        if event.text.strip():
            self.blocks += [Body(event.text, role=ThinkingRole), Gap()]

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript) -> None:
        route = event.route
        targets = ", ".join(route.targets)
        self.divider(f"{route.sender} → {targets}" if targets else route.sender,
                     event.timestamp, IncomingRole)
        self.blocks += [Body(event.text, bar=IncomingRole), Gap()]

    @handles(SentTranscript)
    def sent(self, event: SentTranscript) -> None:
        reply = event.routing.reply if event.routing is not None else None
        targets = ", ".join(reply.targets) if reply is not None else ""
        self.divider(f"Sent → {targets}" if targets else "Sent", event.timestamp, OutgoingRole)
        self.blocks += [Body(event.text, bar=OutgoingRole), Gap()]
