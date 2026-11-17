"""Toad's line blocks as Qt rich text: the blocks RichLineRenderer paints for Textual,
in the same roles and the same theme colours."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from pygments.lexers import get_lexer_by_name
from pygments.token import _TokenType
from pygments.util import ClassNotFound
from PySide6.QtGui import QFont, QFontMetricsF
from rich.style import Style
from rich.syntax import ANSI_DARK, ANSI_LIGHT
from ui_theme.colour import require_terminal_palette

from markdown_it import MarkdownIt
from metaclass_registry.mro_dispatch import handles
from ui_theme.scheme import ColourScheme, ThemeColour

from toad.client.line_blocks import (
    Body,
    Divider,
    Gap,
    LineBlock,
    LineRole,
    NoBar,
    Span,
    SpanColumns,
    Spans,
    Summary,
)
from toad.core.projection import MroProjection
from toad.message_rows import DividerLine, DrawsDividers, LineRoom, WireBody


@dataclass(frozen=True)
class PixelRoom(LineRoom):
    """A divider line in a Qt view: its width in pixels of the divider's bold font, keeping room
    for a short rule on each side of every line."""

    metrics: QFontMetricsF
    width: float

    MIN_RULE = 2

    def measure(self, text: str) -> float:
        return self.metrics.horizontalAdvance(text)

    @property
    def rule_width(self) -> float:
        return self.metrics.horizontalAdvance("─")

    @property
    def capacity(self) -> float:
        return max(1.0, self.width - self.measure("    ") - 2 * self.MIN_RULE * self.rule_width)

    def fits(self, spans: tuple[Span, ...]) -> bool:
        return self.measure("".join(span.text for span in spans)) <= self.capacity

    def rules(self, spans: tuple[Span, ...]) -> tuple[int, int]:
        title = self.measure("  " + "".join(span.text for span in spans) + "  ")
        side = max(0, int((self.width - title) / 2 / self.rule_width))
        return side, side


class QtLineRenderer(DrawsDividers, MroProjection[str]):
    """Each block through its most specific declared painter, as a fragment of Qt rich text."""

    def __init__(self, scheme: ColourScheme) -> None:
        self.scheme = scheme
        self.markdown = MarkdownIt("commonmark", {"breaks": True, "highlight": self.highlight})
        self.terminal = scheme.terminal.resolve(require_terminal_palette)
        # Toad draws code in the terminal palette through Rich's ANSI syntax theme.
        self.syntax = ANSI_DARK if scheme.dark else ANSI_LIGHT
        self.width = 0.0
        self.font = QFont()

    def at_width(self, width: float, font: QFont) -> QtLineRenderer:
        """Dividers fill this many pixels of this font, as RichLineRenderer fills its cells."""
        self.width, self.font = width, font
        return self

    def token_style(self, token: _TokenType) -> Style:
        """The nearest declared ancestor's style: Rich's theme names token families."""
        return next((self.syntax[kind] for kind in (token, *token.split()[::-1]) if kind in self.syntax), Style())

    def token_css(self, token: _TokenType) -> str:
        style = self.token_style(token)
        css = ([f"color:{self.terminal.ansi[style.color.number].hex}"]
               if style.color is not None and style.color.number is not None else [])
        css += ["font-weight:bold"] * bool(style.bold) + ["font-style:italic"] * bool(style.italic)
        return ";".join(css)

    def highlight(self, code: str, language: str, attributes: str) -> str:
        """A fenced block in its language's colours, as Toad highlights code; an unknown
        language or a bare fence stays plain."""
        try:
            lexer = get_lexer_by_name(language)
        except ClassNotFound:
            return ""
        spans = "".join(f'<span style="{self.token_css(token)}">{escape(text)}</span>'
                        for token, text in lexer.get_tokens(code))
        return f"<pre>{spans}</pre>"

    def colour(self, role: type[LineRole]) -> str:
        return self.theme(role.colour)

    def theme(self, member: type[ThemeColour]) -> str:
        """A theme colour under this scheme, as Toad resolves it."""
        return member.rgb(self.scheme).hex

    def styled(self, text: str, role: type[LineRole]) -> str:
        css = [f"color:{self.colour(role)}"]
        css += ["font-weight:bold"] * role.bold + ["font-style:italic"] * role.italic
        css += ["text-decoration:underline"] * role.underline
        return f'<span style="{";".join(css)}">{escape(text)}</span>'

    def span(self, span: Span, role: type[LineRole]) -> str:
        return self.styled(span.text, role)

    def html(self, blocks: tuple[LineBlock, ...]) -> str:
        return "".join(self.project_value(block) for block in blocks)

    # The divider is drawn by DrawsDividers; these say how rich text draws one line. Its
    # lines are one paragraph with no margins, so no space opens between title and time,
    # and the Gap before every header is its only space above, one row as Textual draws.

    def divider_room(self) -> PixelRoom:
        bold = QFont(self.font)
        bold.setBold(True)
        return PixelRoom(QFontMetricsF(bold), self.width)

    def ruled_line(self, line: DividerLine, block: Divider) -> str:
        before = self.styled("─" * line.before, block.role)
        after = self.styled("─" * line.after, block.role)
        return f"{before} <b>{self.title(line.spans, block)}</b> {after}"

    def joined_divider(self, lines: tuple[str, ...]) -> str:
        return ('<p align="center" style="margin:0;white-space:pre">'
                + "<br/>".join(lines) + "</p>")

    def title(self, spans: tuple[Span, ...], block: Divider) -> str:
        return "".join(self.span(span, span.link.heading_role(span.role, block.role)) for span in spans)

    @handles(Gap)
    def gap(self, block: Gap) -> str:
        """One empty row, as Textual's gap is: no paragraph margins added to it."""
        return '<p style="margin:0">&nbsp;</p>'

    @handles(Summary)
    def summary(self, block: Summary) -> str:
        """One row: the kept spans' room is reserved and the rest elides at the row's end."""
        return ('<p style="white-space:pre">' + "".join(self.span(span, span.role) for span in block.spans)
                + "".join(self.span(span, span.role) for span in block.kept) + "</p>")

    @handles(SpanColumns)
    def span_columns(self, block: SpanColumns) -> str:
        """Cells flow into columns at the drawing width, as Qt rich text wraps inline cells."""
        cells = "&nbsp;&nbsp;".join(
            '<span style="white-space:pre">' + "".join(self.span(span, span.role) for span in cell) + "</span>"
            for cell in block.cells)
        return f'<p style="margin-left:{block.indent}ch">{cells}</p>'

    @handles(Spans)
    def spans(self, block: Spans) -> str:
        return "<p>" + "".join(self.span(span, span.role) for span in block.spans) + "</p>"

    @handles(WireBody)
    def wire_body(self, block: WireBody) -> str:
        return self.body(Body(block.text, bar=block.bar))

    @handles(Body)
    def body(self, block: Body) -> str:
        text = f'<div style="color:{self.colour(block.role)}">{self.markdown.render(block.text)}</div>'
        if block.bar is NoBar:
            return text
        return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                f'<td width="3" style="background-color:{self.colour(block.bar)}"></td>'
                f'<td style="padding-left:8px">{text}</td></tr></table>')
