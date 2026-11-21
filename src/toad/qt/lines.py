"""Toad's line blocks as Qt rich text: the blocks RichLineRenderer paints for Textual,
in the same roles and the same theme colours, through the same `LineBlockPainter` contract."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from markdown_it import MarkdownIt
from metaclass_registry.mro_dispatch import handles
from pygments.lexers import get_lexer_by_name
from pygments.token import _TokenType
from pygments.util import ClassNotFound
from PySide6.QtWidgets import QWidget
from rich.cells import cell_len
from rich.style import Style
from rich.syntax import ANSI_DARK, ANSI_LIGHT
from ui_theme.colour import require_terminal_palette
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
from toad.core.projection import MroProjection
from toad.markdown_links import LinkContext, MessageMarkdownParser
from toad.message_rows import DIVIDER_TIME, WireBody
from toad.patch import (
    DiffSettings,
    NoPatchCell,
    Patch,
    PatchCell,
    SplitRows,
    UnifiedRows,
)
from toad.rich_preparation import RichTextBody, palette_colour
from toad.widgets.transcript_lines import CellRoom


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

    def __init__(self, scheme: ColourScheme, links: LinkContext, diff: DiffSettings) -> None:
        self.links = links
        self.followers: list[Callable[[], None]] = []
        """What repaints when this renderer's scheme or diff marks change (`follows_theme`)."""
        # HTML emission only; a source line break stays a line, as Rich draws soft breaks.
        self.markdown = MarkdownIt("gfm-like", {"breaks": True, "highlight": self.highlight})
        self.markdown.renderer.rules["link_open"] = self.link_open
        self.follow(scheme, diff)
        self.width = 1

    def follow(self, scheme: ColourScheme, diff: DiffSettings) -> None:
        """Draw under this scheme with these diff settings from now on (`ui.theme`, `diff`).
        The app's renderer is the one its widgets hold; a preparation already on the pool
        keeps the copy it was handed (`bound`)."""
        self.scheme = scheme
        self.diff = diff
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
        """An independent data renderer for one preparation.

        Constructing it from declarations instead of copying the live renderer keeps
        followers, widgets and Markdown parser state out of the process boundary.
        """
        bound = type(self)(self.scheme, self.links, self.diff)
        bound.__dict__.update(fields)
        return bound

    def at_width(self, width: int) -> QtLineRenderer:
        """Draw at this many monospace cells, the same width authority Textual uses."""
        return self.bound(width=max(1, width))

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
        room = CellRoom(self.width)
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
        longest = max((cell_len(line.expandtabs(4))
                       for line in (*block.before.values(), *block.after.values())), default=0)
        required = 2 * (longest + block.number_width + 4) + 3
        rows = self.diff.view.rows_at(self.width, required)
        return QtPatchPainter(self, block).project_value(rows)

    def patch_line(self, gutter: str, code: str, role: type[LineRole], language: str) -> str:
        """One diff row on its role's tint, its code in its language's colours."""
        colour = self.colour(role).lstrip("#")
        red, green, blue = (int(colour[index:index + 2], 16) for index in (0, 2, 4))
        background = f"rgba({red},{green},{blue},{role.background_tint:.2f})"
        return (f'<span style="background-color:{background}">{self.styled(gutter, role.gutter())}'
                f'{self.code_spans(code, language) or self.styled(code, role)}</span>\n')

    @handles(RichTextBody)
    def rich_text(self, block: RichTextBody) -> str:
        text = "".join(f'<span style="{self.style_css(segment.style or Style())}">{escape(segment.text)}</span>'
                       for segment in block.segments)
        return self.barred(f'<pre style="color:{self.colour(block.role)}">{text}</pre>', block.bar)


class QtPatchSide(MroProjection[str]):
    """One declared side of a Qt diff row: code, or the absent member."""

    def __init__(self, renderer: QtLineRenderer, patch: Patch) -> None:
        self.renderer, self.patch = renderer, patch

    @handles(PatchCell)
    def cell(self, cell: PatchCell, gutter: str) -> str:
        return self.renderer.patch_line(gutter, cell.selected().expandtabs(4), cell.role, self.patch.language)

    @handles(NoPatchCell)
    def absent(self, cell: NoPatchCell, gutter: str) -> str:
        return self.renderer.styled(gutter + " ", MutedRole)


class QtPatchPainter(MroProjection[str]):
    """The shared diff-row family drawn in Qt, under the same view and wrap declarations as Textual."""

    def __init__(self, renderer: QtLineRenderer, patch: Patch) -> None:
        self.renderer, self.patch = renderer, patch
        self.side = QtPatchSide(renderer, patch)

    @property
    def white_space(self) -> str:
        return self.renderer.diff.wrap.css_white_space

    def table(self, body: str) -> str:
        title = self.renderer.styled(self.patch.title, MutedRole)
        return (f'<p style="white-space:{self.white_space}">{title}</p>'
                f'<table cellspacing="0" cellpadding="0" style="white-space:{self.white_space}">{body}</table>')

    @handles(UnifiedRows)
    def unified(self, rows: UnifiedRows) -> str:
        width = self.patch.number_width
        groups = []
        for group in self.patch.row_groups(rows):
            rendered = []
            for before, after in group:
                cell = before.otherwise(after)
                gutter = f"{before.label:>{width}} {after.label:>{width}} {self.renderer.diff.marks.prefix(cell.role)}"
                rendered.append(f'<tr><td>{self.side.project_value(cell, gutter)}</td></tr>')
            groups.append("".join(rendered))
        separator = f'<tr><td>{self.renderer.styled("…", MutedRole)}</td></tr>'
        return self.table(separator.join(groups))

    @handles(SplitRows)
    def split(self, rows: SplitRows) -> str:
        width = self.patch.number_width
        groups = []
        for group in self.patch.row_groups(rows):
            rendered = []
            for before, after in group:
                left = f"{before.label:>{width}} {self.renderer.diff.marks.prefix(before.role)}"
                right = f"{after.label:>{width}} {self.renderer.diff.marks.prefix(after.role)}"
                rendered.append(f'<tr><td>{self.side.project_value(before, left)}</td>'
                                f'<td>{self.side.project_value(after, right)}</td></tr>')
            groups.append("".join(rendered))
        separator = (f'<tr><td>{self.renderer.styled("…", MutedRole)}</td>'
                     f'<td>{self.renderer.styled("…", MutedRole)}</td></tr>')
        return self.table(separator.join(groups))
