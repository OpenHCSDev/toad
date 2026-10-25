"""What a committed transcript fragment shows, independent of any frontend.

A fragment becomes a few line blocks. Blocks carry text and semantic roles;
a frontend maps roles to its own styles and renders the blocks. Nothing here
imports a terminal or rendering library.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import json
import re
from urllib.parse import quote, unquote

from agent_comms.declared_family import DeclaredFamily
from agent_comms.display_references import DisplayReference
from agent_comms.field_codec import FieldCodec

from typing import ClassVar

from ui_theme.scheme import (
    AccentColour, ErrorColour, ForegroundColour, MutedColour, PrimaryColour, SecondaryColour, SuccessColour,
    ThemeColour, WarningColour,
)

class LineRole(DeclaredFamily, affix="Role"):
    """The meaning of a piece of text, and the theme colour it is drawn in."""

    colour: ClassVar[type[ThemeColour]] = ForegroundColour
    italic: ClassVar[bool] = False
    bold: ClassVar[bool] = False
    underline: ClassVar[bool] = False
    diff_marker: ClassVar[str] = " "
    background_tint: ClassVar[float] = 0


class TextRole(LineRole):
    """Ordinary message text."""


class MutedRole(LineRole):
    """Secondary text: summaries, collapsed disclosures."""

    colour = MutedColour


class ThinkingRole(MutedRole):
    """Visible reasoning stays muted and italic, distinct from tool success."""

    italic = True


class UserRole(LineRole):
    # A user message, live (UserInput) or committed, is a Body with this bar.
    colour = SecondaryColour


class AgentRole(LineRole):
    colour = PrimaryColour


class ToolVerbRole(AgentRole):
    """The operation a tool performs, distinct from its argument."""

    bold = True


class ToolArgumentRole(LineRole):
    """The path, command or other argument shown by a tool."""


class ToolOutputRole(LineRole):
    """Output disclosed beneath a tool call."""

    colour = SecondaryColour


class SuccessRole(LineRole):
    colour = SuccessColour
    bold = True


class FailureRole(LineRole):
    colour = ErrorColour
    bold = True


class AddedCodeRole(LineRole):
    """A reported added line, distinct from a tool's success status."""

    colour = SuccessColour
    diff_marker = "+"
    background_tint = .16


class RemovedCodeRole(LineRole):
    """A reported removed line, distinct from a failed tool."""

    colour = ErrorColour
    diff_marker = "−"
    background_tint = .16


class IncomingRole(LineRole):
    """A message received from another participant."""

    colour = AccentColour


class OutgoingRole(LineRole):
    """A message sent to another participant."""

    colour = SuccessColour


class GreenTextRole(LineRole):
    """A quoted line, drawn as greentext."""

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


class LineLink(DeclaredFamily, affix="Link"):
    """What clicking a piece of text does; the widget that drew it opens each kind of link."""

    # Whether the text is underlined to show that it leads somewhere.
    underlined: ClassVar[bool] = True

    @property
    def click(self) -> str | tuple[str, tuple]:
        return "open", (self,)

    async def copy_menu(self, widget, event):
        return False

    @property
    def encoded_href(self) -> str:
        """Encode only for a dependency's string-only action boundary."""
        return "toad-link:" + quote(json.dumps(FieldCodec.encode(self)), safe="")

    def inline_tokens(self, content):
        from markdown_it.token import Token
        return (Token("link_open", "a", 1, attrs={"href": LinkHref.capture(self)}),
                content, Token("link_close", "a", -1))

    @classmethod
    def from_href(cls, href: str) -> LineLink:
        if not href.startswith("toad-link:"):
            raise ValueError("Expected a resolved Markdown action")
        return FieldCodec.decode(cls, json.loads(unquote(href.removeprefix("toad-link:"))))


class LinkHref(str):
    """Keep the typed action through Rich's str(href); Textual uses the encoded string.

    Rich's Markdown unconditionally calls str() and then retains the resulting
    value in Style.link. Returning this string preserves the action without a
    second parser or a per-render lookup table. Pickle carries the same value.
    """
    def __new__(cls, value, target):
        href = super().__new__(cls, value)
        href.target = target
        return href

    @classmethod
    def capture(cls, target):
        return cls(target.encoded_href, target)

    def __str__(self):
        return self

    def __getnewargs__(self):
        return (super().__str__(), self.target)


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
class OpenReference(LineLink):
    """Core's exact display identity, not a delivery mention."""

    reference: DisplayReference


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

    @property
    def retained_bytes(self) -> int:
        """Record plus Unicode payload; not a census of shared theme objects."""
        return 64 + 4 * len(self.selection_text)

    def prepared_rows[RowsT](self, width: int, draw: Callable[[LineBlock], RowsT]) -> RowsT:
        return draw(self)

    @property
    def selection_text(self) -> str:
        return ""


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

    @property
    def selection_text(self) -> str:
        return self.label


@dataclass(frozen=True)
class SpanText(LineBlock):
    """Text made of spans; subclasses decide whether it wraps or clips."""

    spans: tuple[Span, ...]

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)

    @property
    def selection_text(self) -> str:
        return self.text


@dataclass(frozen=True)
class Spans(SpanText):
    """Wrapped text made of spans; line breaks in the text are kept."""

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
class SpanColumns(LineBlock):
    """Complete span cells flow into columns at the available drawing width.

    Unlike Spans, these breaks separate cells, not forced visual rows. Links
    and roles stay on their original spans however the frontend lays them out.
    """

    cells: tuple[tuple[Span, ...], ...]
    indent: int = 0

    @property
    def selection_text(self) -> str:
        return "\n".join("".join(span.text for span in cell) for cell in self.cells)


@dataclass(frozen=True)
class Summary(SpanText):
    """One clipped row, followed by spans whose space is reserved first."""

    kept: tuple[Span, ...] = ()

    @property
    def text(self) -> str:
        return super().text + "".join(span.text for span in self.kept)

    @classmethod
    def titled(cls, title: str, role: type[LineRole] = MutedRole,
               link: LineLink | None = None) -> Summary:
        return cls((Span(title, role, link),))

    @property
    def selection_text(self) -> str:
        return self.text


@dataclass(frozen=True)
class Gap(LineBlock):
    """One blank line between messages."""


@dataclass(frozen=True)
class Body(LineBlock):
    """Plain text, optionally marked by a bar in another role."""

    text: str
    role: type[LineRole] = TextRole
    bar: type[LineRole] | None = None

    @property
    def selection_text(self) -> str:
        return self.text

    def prepare(self, markdown: Callable[[Body], LineBlock]) -> LineBlock:
        return self


class MarkdownBody(Body):
    def prepare(self, markdown: Callable[[Body], LineBlock]) -> LineBlock:
        return markdown(self)

    @classmethod
    def code(cls, text: str, language: str = "", **shown) -> Body:
        """Text drawn as it is written, in a language's colours when the language is known."""
        ticks = "`" * max(3, 1 + max(map(len, re.findall("`+", text)), default=0))
        return cls(f"{ticks}{language}\n{text}\n{ticks}", **shown)
