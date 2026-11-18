"""Toad's line blocks as Qt rich text: the blocks RichLineRenderer paints for Textual,
in the same roles and the same theme colours, through the same `LineBlockPainter` contract."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from html import escape

from pygments.lexers import get_lexer_by_name
from pygments.token import _TokenType
from pygments.util import ClassNotFound
from PySide6.QtGui import QColor, QFont, QFontMetricsF
from PySide6.QtWidgets import QWidget
from rich.style import Style
from rich.syntax import ANSI_DARK, ANSI_LIGHT
from ui_theme.colour import require_terminal_palette

from markdown_it import MarkdownIt
from metaclass_registry.mro_dispatch import handles
from ui_theme.scheme import ColourScheme, RuleColour, ThemeColour

from toad.client.line_blocks import (
    Body,
    Divider,
    Gap,
    LineBlock,
    LineLink,
    LineRole,
    MarkdownBody,
    MutedRole,
    NoBar,
    NoLink,
    Span,
    SpanColumns,
    Spans,
    Summary,
)
from toad.client.line_painting import LineBlockPainter, LinkPresentation
from toad.markdown_links import LinkContext, MessageMarkdownParser
from toad.message_rows import DIVIDER_TIME, LineRoom, WireBody
from toad.patch import DiffMarks, Patch
from toad.rich_preparation import RichTextBody, palette_colour


@dataclass(frozen=True)
class PixelRoom(LineRoom):
    """A divider line in a Qt view: its width in pixels of the divider's bold font, keeping room
    for a short rule on each side."""

    metrics: QFontMetricsF
    width: float

    def advance(self, spans: tuple[Span, ...]) -> float:
        return self.metrics.horizontalAdvance("  " + "".join(span.text for span in spans) + "  ")

    def rule(self, spans: tuple[Span, ...]) -> int:
        """Rule characters for each side of these spans; under two, the line has no room for rules."""
        return int((self.width - self.advance(spans)) / 2 / self.metrics.horizontalAdvance("─"))

    def fits(self, spans: tuple[Span, ...]) -> bool:
        return self.rule(spans) >= 2


class QtLinkMarkup(LinkPresentation[tuple[str, str]]):
    """The anchor around linked text, as Textual's `LinkStyle` gives it a click action."""

    @handles(LineLink)
    def linked(self, link: LineLink, colour: str) -> tuple[str, str]:
        decoration = "underline" if link.underlined else "none"
        return f'<a href="{escape(link.encoded_href)}" style="color:{colour};text-decoration:{decoration}">', "</a>"

    @handles(NoLink)
    def plain(self, link: NoLink, colour: str) -> tuple[str, str]:
        return "", ""


QT_LINK_MARKUP = QtLinkMarkup()


class QtLineRenderer(LineBlockPainter[str]):
    """Each shared block as a fragment of Qt rich text; Markdown through the shared parser."""

    def __init__(self, scheme: ColourScheme, links: LinkContext, diff_marks: DiffMarks) -> None:
        self.links = links
        self.followers: list[Callable[[], None]] = []
        """What repaints when this renderer's scheme or diff marks change (`follows_theme`)."""
        # HTML emission only; a source line break stays a line, as Rich draws soft breaks.
        self.markdown = MarkdownIt("gfm-like", {"breaks": True, "highlight": self.highlight})
        self.markdown.renderer.rules["link_open"] = self.link_open
        self.follow(scheme, diff_marks)
        self.width = 0.0
        self.font = QFont()

    def follow(self, scheme: ColourScheme, diff_marks: DiffMarks) -> None:
        """Draw under this scheme with these diff marks from now on (`ui.theme`, `diff`).
        The app's renderer is the one its widgets hold; a preparation already on the pool
        keeps the copy it was handed (`bound`)."""
        self.scheme = scheme
        self.diff_marks = diff_marks
        self.terminal = scheme.terminal.resolve(require_terminal_palette)
        # Toad draws code in the terminal palette through Rich's ANSI syntax theme.
        self.syntax = ANSI_DARK if scheme.dark else ANSI_LIGHT
        for repaint in tuple(self.followers):
            repaint()

    @staticmethod
    def apply_sheet(widget: QWidget, sheet: str) -> None:
        """Give ``widget`` this style sheet. Qt repolishes a widget and asks its parents to
        lay out again on every `setStyleSheet`, even with the sheet it already has, so a
        line restyled on each status update or focus change re-laid out the composer each
        time; an unchanged sheet now costs nothing."""
        if widget.styleSheet() != sheet:
            widget.setStyleSheet(sheet)

    def themed(self, widget: QWidget, paint: Callable[[], None]) -> None:
        """``paint`` draws ``widget``'s own colours from this renderer's scheme: now, and
        again each time the scheme changes. Colours set once keep the scheme they were
        built in."""
        paint()
        self.follows_theme(widget, paint)

    def follows_theme(self, widget: QWidget, repaint: Callable[[], None]) -> None:
        """``repaint`` runs each time `ui.theme` or the `diff` settings change this renderer
        (`follow`), until ``widget`` goes."""
        self.followers.append(repaint)
        widget.destroyed.connect(lambda: self.followers.remove(repaint))

    def bound(self, **fields) -> QtLineRenderer:
        """A copy for one pool preparation, so concurrent widths and link contexts don't clash."""
        bound = copy.copy(self)
        bound.__dict__.update(fields)
        return bound

    def at_width(self, width: float, font: QFont) -> QtLineRenderer:
        """Dividers fill this many pixels of this font, as RichLineRenderer fills its cells."""
        return self.bound(width=width, font=font)

    def with_links(self, links: LinkContext) -> QtLineRenderer:
        return self.bound(links=links)

    def token_style(self, token: _TokenType) -> Style:
        """The nearest declared ancestor's style: Rich's theme names token families."""
        return next((self.syntax[kind] for kind in (token, *token.split()[::-1]) if kind in self.syntax), Style())

    def style_css(self, style: Style) -> str:
        colour = palette_colour(style, self.terminal.ansi)
        css = [f"color:{colour}"] * (colour is not None)
        css += ["font-weight:bold"] * bool(style.bold) + ["font-style:italic"] * bool(style.italic)
        css += ["text-decoration:underline"] * bool(style.underline)
        return ";".join(css)

    def token_css(self, token: _TokenType) -> str:
        return self.style_css(self.token_style(token))

    def highlight(self, code: str, language: str, attributes: str) -> str:
        """A fenced block in its language's colours, as Toad highlights code; an unknown
        language or a bare fence stays plain."""
        spans = self.code_spans(code, language)
        return f"<pre>{spans}</pre>" if spans else ""

    def code_spans(self, code: str, language: str) -> str:
        """Code in its language's colours; "" when the language is unknown."""
        try:
            lexer = get_lexer_by_name(language, stripnl=False, ensurenl=False)
        except ClassNotFound:
            return ""
        return "".join(f'<span style="{self.token_css(token)}">{escape(text)}</span>'
                       for token, text in lexer.get_tokens(code))

    def colour(self, role: type[LineRole]) -> str:
        return self.theme(role.colour)

    def color_style(self, role: type[LineRole]) -> str:
        """The QSS color declaration for a role, as Qt consumers set it on a widget."""
        return f"color: {self.colour(role)}"

    def theme(self, member: type[ThemeColour]) -> str:
        """A theme colour under this scheme, as Toad resolves it."""
        return member.rgb(self.scheme).hex

    def styled(self, text: str, role: type[LineRole]) -> str:
        css = [f"color:{self.colour(role)}"]
        css += ["font-weight:bold"] * role.bold + ["font-style:italic"] * role.italic
        css += ["text-decoration:underline"] * role.underline
        return f'<span style="{";".join(css)}">{escape(text)}</span>'

    def span(self, span: Span, role: type[LineRole]) -> str:
        """A span in a role, inside its link's anchor when it leads somewhere."""
        start, end = QT_LINK_MARKUP.project_value(span.link, self.colour(role))
        return f"{start}{self.styled(span.text, role)}{end}"

    def link_open(self, tokens, index: int, options, env) -> str:
        link = tokens[index].attrs["href"].target
        return QT_LINK_MARKUP.project_value(link, self.colour(QT_LINK_MARKUP.markdown_role))[0]

    def html(self, blocks: tuple[LineBlock, ...]) -> str:
        return "".join(self.project_value(block) for block in blocks)

    def barred(self, text: str, bar: type[LineRole]) -> str:
        """Content behind its accent bar, as Textual's `_body_rows` prefixes each row."""
        if bar is NoBar:
            return text
        return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                f'<td width="3" style="background-color:{self.colour(bar)}"></td>'
                f'<td style="padding-left:8px">{text}</td></tr></table>')

    @handles(Divider)
    def divider(self, block: Divider) -> str:
        """Every row of the title flanked by rules filling the width, as Textual's divider does.
        A terminal can only draw its rule in whole `─` cells; Qt draws each side as a real line
        reaching the edge, so every rule spans the full width whatever the title's length.
        The title's cell takes its content's width and the side cells share the rest."""
        bold = QFont(self.font)
        bold.setBold(True)
        room = PixelRoom(QFontMetricsF(bold), self.width)
        groups = [row for group in DIVIDER_TIME.project_value(block.timestamp, block.spans, room)
                  for row in room.wrapped(group)]
        colour = self.theme(RuleColour)
        rule = f'<td valign="middle"><hr style="background-color:{colour};color:{colour}"/></td>'
        rows = "".join(f'<tr>{rule}<td width="1" valign="middle" style="white-space:pre">'
                       f'&nbsp;<b>{self.title(group, block)}</b>&nbsp;</td>{rule}</tr>'
                       for group in groups)
        return f'<table width="100%" cellspacing="0" cellpadding="0">{rows}</table>'

    def title(self, spans: tuple[Span, ...], block: Divider) -> str:
        return "".join(self.span(span, span.link.heading_role(span.role, block.role)) for span in spans)

    @handles(Gap)
    def gap(self, block: Gap) -> str:
        return "<p>&nbsp;</p>"

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
        return ('<p style="white-space:pre-wrap">'
                + "".join(self.span(span, span.role) for span in block.spans) + "</p>")

    @handles(WireBody)
    def wire_body(self, block: WireBody) -> str:
        return self.project_value(block.prepared_in(self.links))

    @handles(Body)
    def body(self, block: Body) -> str:
        """Plain text, as written."""
        return self.coloured(f'<p style="white-space:pre-wrap">{escape(block.text)}</p>', block)

    @handles(MarkdownBody)
    def markdown_body(self, block: MarkdownBody) -> str:
        """Markdown or code: the block's own `prepare` hands its Markdown source to `marked`."""
        return block.prepare(self.marked)

    def marked(self, block: Body) -> str:
        """Markdown through the shared parser: paths, @mentions and links resolved."""
        tokens = MessageMarkdownParser(self.links).parse(block.text)
        return self.coloured(self.markdown.renderer.render(tokens, self.markdown.options, {}), block)

    def coloured(self, html: str, block: Body) -> str:
        return self.barred(f'<div style="color:{self.colour(block.role)}">{html}</div>', block.bar)

    @handles(Patch)
    def patch(self, block: Patch) -> str:
        groups = self.styled("…\n", MutedRole).join(
            "".join(self.patch_line(gutter, code, role, block.language) for gutter, code, role in group)
            for group in block.unified_lines(self.diff_marks))
        return f'<p style="white-space:pre">{self.styled(block.title, MutedRole)}</p><pre>{groups}</pre>'

    def patch_line(self, gutter: str, code: str, role: type[LineRole], language: str) -> str:
        """One diff row on its role's tint, its code in its language's colours."""
        tint = QColor(self.colour(role))
        tint.setAlphaF(role.background_tint)
        background = f"rgba({tint.red()},{tint.green()},{tint.blue()},{tint.alphaF():.2f})"
        return (f'<span style="background-color:{background}">{self.styled(gutter, role.gutter())}'
                f'{self.code_spans(code, language) or self.styled(code, role)}</span>\n')

    @handles(RichTextBody)
    def rich_text(self, block: RichTextBody) -> str:
        text = "".join(f'<span style="{self.style_css(segment.style or Style())}">{escape(segment.text)}</span>'
                       for segment in block.segments)
        return self.barred(f'<pre style="color:{self.colour(block.role)}">{text}</pre>', block.bar)
