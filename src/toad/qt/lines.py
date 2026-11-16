"""Toad's line blocks as Qt rich text: the blocks RichLineRenderer paints for Textual,
in the same roles and the same theme colours."""

from __future__ import annotations

from html import escape

from pygments.lexers import get_lexer_by_name
from pygments.token import _TokenType
from pygments.util import ClassNotFound
from PySide6.QtGui import QFont, QFontMetricsF
from rich.style import Style
from rich.syntax import ANSI_DARK, ANSI_LIGHT
from ui_theme.colour import require_terminal_palette

from agent_comms.storage.recorded_time import RecordedEventTime, UnrecordedEventTime
from markdown_it import MarkdownIt
from metaclass_registry.mro_dispatch import handles
from ui_theme.scheme import ColourScheme, ThemeColour

from toad.client.line_blocks import Body, Divider, LineBlock, LineRole, NoBar, Span, Spans
from toad.core.projection import MroProjection
from toad.message_rows import RecordedMessageClock, WireBody


class QtDividerTime(MroProjection[str]):
    """A recorded divider shows its time after the title; an unrecorded one shows none."""

    @handles(RecordedEventTime)
    def recorded(self, time: RecordedEventTime) -> str:
        return f" · {RecordedMessageClock(time.at).display()[0]}"

    @handles(UnrecordedEventTime)
    def unrecorded(self, time: UnrecordedEventTime) -> str:
        return ""


QT_DIVIDER_TIME = QtDividerTime()


class QtLineRenderer(MroProjection[str]):
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

    @handles(Divider)
    def divider(self, block: Divider) -> str:
        title = "".join(self.span(span, span.link.heading_role(span.role, block.role)) for span in block.spans)
        time = QT_DIVIDER_TIME.project_value(block.timestamp)
        bold = QFont(self.font)
        bold.setBold(True)
        measure = QFontMetricsF(bold)
        label = f"  {block.label}{time}  "
        side = max(2, int((self.width - measure.horizontalAdvance(label)) / 2 / measure.horizontalAdvance("─")))
        rule = self.styled("─" * side, block.role)
        return (f'<p align="center" style="margin-top:10px;white-space:pre">{rule} <b>{title}</b>'
                f'{self.styled(time, block.role)} {rule}</p>')

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
