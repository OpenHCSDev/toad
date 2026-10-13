"""What a committed transcript fragment shows, independent of any frontend.

A fragment becomes a few line blocks. Blocks carry text and semantic roles;
a frontend maps roles to its own styles and renders the blocks. Nothing here
imports a terminal or rendering library.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re

from typing import ClassVar

from ui_theme.scheme import (
    AccentColour, ForegroundColour, MutedColour, PrimaryColour, SecondaryColour, SuccessColour,
    ThemeColour, WarningColour,
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
    """What clicking a piece of text does; the widget that drew it opens each kind of link."""

    # Whether the text is underlined to show that it leads somewhere.
    underlined: ClassVar[bool] = True

    @property
    def click(self) -> str | tuple[str, tuple]:
        return "open", (self,)


@dataclass(frozen=True)
class OpenTarget(LineLink):
    """Open a thread or channel."""

    target: str


@dataclass(frozen=True)
class OpenHistoricalTarget(LineLink):
    """Open a thread as an attached history source recorded it."""

    target: str
    source: str


@dataclass(frozen=True)
class OpenUrl(LineLink):
    """Open an address written in a message: a web page, a mail address, a file."""

    url: str
    # An address that would run code instead of opening something is never a link.
    runs_code: ClassVar[re.Pattern[str]] = re.compile(r"\s*(vbscript|javascript|data):", re.IGNORECASE)

    @classmethod
    def opens(cls, url: str) -> bool:
        """Whether `[label](url)` is drawn as a link, in every style a message is drawn in."""
        return cls.runs_code.match(url) is None

    @property
    def click(self) -> str:
        # The action a Markdown link runs, so one handler opens an address however it was written.
        return f"link({self.url!r})"


@dataclass(frozen=True)
class ToggleDetails(LineLink):
    """Show or hide the details of the fragment this is drawn in."""

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
    """A rule carrying a title: who speaks, or who sent a message to whom.

    Title text without a link is drawn in the rule's role; a linked span keeps
    its own. The frontend formats the time.
    """

    spans: tuple[Span, ...]
    role: type[LineRole]
    timestamp: float | None = None

    @classmethod
    def titled(cls, title: str, role: type[LineRole], timestamp: float | None = None) -> Divider:
        return cls((Span(title),), role, timestamp)

    @property
    def label(self) -> str:
        return "".join(span.text for span in self.spans)


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

    @classmethod
    def from_lines(cls, lines: tuple[tuple[Span, ...], ...], indent: str = "") -> "Spans":
        """One block out of lines of spans, each line starting at ``indent``."""
        drawn: list[Span] = []
        for index, line in enumerate(lines):
            if not line:
                continue
            first, *rest = line
            leading = indent if index == 0 else f"\n{indent}"
            drawn.append(replace(first, text=leading + first.text) if first.text else first)
            drawn.extend(rest)
        return cls(tuple(drawn))


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
