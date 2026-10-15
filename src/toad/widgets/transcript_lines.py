"""The Rich/Textual frontend for transcript line blocks.

`toad.line_blocks` says what a fragment shows. This module decides how it looks
in Textual: a theme maps each role's colour to a style, and a renderer turns each block
into rows. Styled rows are rendered in the render worker processes; until they
arrive a fragment draws plain rows, so a row is never blank.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import cached_property
import io
from itertools import count
from threading import local

from rich.cells import cell_len, set_cell_size
from rich.columns import Columns
from rich._wrap import divide_line
from rich.segment import Segment
from rich.style import Style
from rich.terminal_theme import DEFAULT_TERMINAL_THEME, TerminalTheme
from textual.strip import Strip
from textual.visual import Visual
from textual.widget import Widget
from textual.scroll_view import ScrollView
from textual.geometry import Size
from textual.selection import Selection
from toad.rich_preparation import RichTextBody

from agent_comms.mro_dispatch import MroDispatch, handles
from ui_theme.scheme import MutedColour, ThemeColour
from toad.line_blocks import (
    Body, Divider, Gap, LineBlock, LineLink, LineRole, OpenHistoricalTarget, OpenTarget, OpenUrl, Span, Spans, SpanColumns,
    Summary, MutedRole,
)
from toad.core.input_events import SelectHistoricalIdentity, SelectTarget
from toad.menus import MenuItem
from toad.message_rows import MessageRow
from toad.core_event_carrier import CoreEventReceiver
from toad.navigation_target import linked_target
from toad.render_backend import ReusableRenderTask
from toad.patch import Patch, PatchCell
from toad.preferences import DiffSettings
from toad.rich_preparation import SyntaxPalette

Row = tuple[Segment, ...]


@dataclass(frozen=True)
class LineTheme:
    """Rich styles for the theme colours, resolved once per theme from its CSS variables,
    and the host terminal's colour system (Rich's name for the colour depth)."""

    colours: tuple[tuple[type[ThemeColour], Style], ...]
    color_system: str
    diff: DiffSettings = field(default_factory=DiffSettings)
    syntax: SyntaxPalette = SyntaxPalette(False, True)
    terminal_theme: TerminalTheme = DEFAULT_TERMINAL_THEME

    def style(self, role: type[LineRole]) -> Style:
        from textual.color import Color

        for colour, style in self.colours:
            if colour is role.colour:
                if role.background_tint:
                    base = Color(*self.terminal_theme.background_color)
                    fill = base.blend(Color(*style.color.get_truecolor(self.terminal_theme)), role.background_tint)
                    style += Style(bgcolor=fill.rich_color)
                return style + Style(italic=role.italic or None, bold=role.bold or None,
                                     underline=role.underline or None)
        raise KeyError(f"{role.__name__} asks for {role.colour.__name__}, which the theme lacks")

    def with_colour(self, colour: type[ThemeColour], style: Style) -> LineTheme:
        """This theme with one colour drawn another way, as a fade draws it part of the way through."""
        return replace(self, colours=((colour, style), *self.colours))

    @classmethod
    def of(cls, variables: Mapping[str, str], color_system: str) -> LineTheme:
        from textual.color import Color

        def colour(name: str) -> Style:
            return Style(color=Color.parse(variables[name]).rich_color)

        foreground = Color.parse(variables["foreground"])
        background = Color.parse(variables["background"])
        # Muted text is the foreground part of the way over the background.
        # ANSI colours cannot be blended; the terminal dims them instead.
        muted = (Style(dim=True) if foreground.ansi is not None
                 else Style(color=background.blend(foreground, MutedColour.amount).rich_color))
        return cls(tuple(
            (member, muted if member is MutedColour else colour(member.name))
            for member in ThemeColour.__registry__.values()
        ), color_system)


def link_style(link: LineLink | None) -> Style:
    """The style that makes text run a link's action when clicked."""
    return Style.null() if link is None else Style(
        underline=link.underlined or None, meta={"@click": link.click})


def _fit(text: str, width: int) -> str:
    """A header occupies one physical row, clipped in terminal cells."""
    text = " ".join(_plain_lines(text))
    if width <= 0:
        return ""
    return text if cell_len(text) <= width else set_cell_size(text, width - 1) + "…"


def _text_width(block: Body | RichTextBody, width: int) -> int:
    """The cells a body's text wraps at: the width less its bar."""
    return max(1, width - (2 if block.bar is not None else 0))


def _clickable(rows: list[Row]) -> list[Row]:
    """Give each Markdown link the click action that opens it; Rich marks a link's cells with its address only."""
    def linked(segment: Segment) -> Segment:
        style = segment.style
        if style is None or not style.link:
            return segment
        return Segment(segment.text, style + Style.from_meta({"@click": OpenUrl(style.link).click}), segment.control)

    return [tuple(map(linked, row)) for row in rows]


class _MarkdownParser(local):
    """Rich's Markdown parser, linking the addresses `OpenUrl` opens: left alone it refuses files."""

    def __init__(self) -> None:
        from markdown_it import MarkdownIt

        self.parser = MarkdownIt().enable("strikethrough").enable("table")
        self.parser.validateLink = OpenUrl.opens  # type: ignore[method-assign]


_markdown_parser = _MarkdownParser()


def _markdown(text: str):
    """A message's text as Rich Markdown."""
    from rich.markdown import Markdown

    # Rich parses in its constructor with a parser of its own; parse nothing there.
    markdown = Markdown("")
    markdown.markup, markdown.parsed = text, _markdown_parser.parser.parse(text)
    return markdown


_row_owners = count()


def link_place() -> int:
    """A number for one thing that draws rows (a history fragment, a message being written)."""
    return next(_row_owners)


def _each_link_apart(rows: tuple[Row, ...], place: int) -> tuple[Row, ...]:
    """Rows whose every link is told apart from equal links drawn elsewhere.

    Textual highlights the cells that share the hovered cell's link identity,
    and Rich gives equal styles one identity: two rows naming the same thread
    carried one, so the pointer over one name lit them all. A link here is a
    run of cells with one click action, which wrapping may carry onto the
    next row. Each run is marked with where it is drawn: the number of what
    draws these rows and the run's number within them. The same link drawn
    again by the same owner (restyled text, another width) keeps its mark,
    so it stays highlighted under a pointer that has not moved.
    """
    action, apart, runs = None, Style.null(), count()

    def placed(segment: Segment) -> Segment:
        nonlocal action, apart
        style = segment.style
        click = style.meta.get("@click") if style is not None else None
        if click is None:
            if segment.text.strip():
                action = None
            return segment
        if click != action:
            action, apart = click, Style.from_meta({"drawn": (place, next(runs))})
        return Segment(segment.text, style + apart, segment.control)

    return tuple(tuple(map(placed, row)) for row in rows)


class OpensLinks(CoreEventReceiver, MroDispatch):
    """A widget whose drawn links open what they name: one handler per kind of link."""

    def action_open(self, link: LineLink) -> None:
        """What a click on a drawn link runs (`LineLink.click`); the keyboard calls it too."""
        self.dispatch_sync(link)

    @handles(OpenTarget)
    def open_target(self, link: OpenTarget) -> None:
        self.publish_core(SelectTarget(linked_target(link.target)))

    @handles(OpenHistoricalTarget)
    def open_historical_target(self, link: OpenHistoricalTarget) -> None:
        self.publish_core(SelectHistoricalIdentity(link.target, link.source))

    async def action_link(self, href: str) -> None:
        """What a click on an address runs (`OpenUrl.click`): a file opens its preview, anything else the browser."""
        from toad.project_path_owner import ProjectPathOwner

        await ProjectPathOwner.link_from(self, href).preview(self)


class OpensMessageNames(OpensLinks):
    """A block the cursor rests on while it draws a bus message: what the message's menu (`MessageRow.menu`) runs."""

    # The message under the cursor.
    message_row: MessageRow

    def action_open_sender(self) -> None:
        self.action_open(self.message_row.sender)

    def action_open_destination(self) -> None:
        self.action_open(self.message_row.destination)


class MessageRowBlock(OpensMessageNames):
    """A widget that is one bus message under the cursor: it offers the message's menu."""

    def get_block_menu(self) -> tuple[MenuItem, ...]:
        return self.message_row.menu


def selection_painted(widget: Widget, strip: Strip, row: int) -> Strip:
    """The canonical paint-time selection projection for drawn rows.

    The live selection is read last, never cached: a selected row takes the
    screen's selection component over its span, and an unselected row is
    returned unchanged.
    """
    selection = widget.text_selection
    if selection is None:
        return strip
    span = selection.get_span(row)
    if span is None:
        return strip
    start, end = span
    if end == -1:
        end = strip.cell_length
    start, end = max(0, start), min(end, strip.cell_length)
    # The fork's divide yields only the pieces before each cut, so the strip's
    # own end is the final cut that keeps the tail.
    cuts = sorted({cut for cut in (start, end, strip.cell_length) if 0 < cut <= strip.cell_length})
    pieces = strip.divide(cuts) if cuts else [strip]
    head, body, tail = [], [], []
    position = 0
    for piece in pieces:
        following = position + piece.cell_length
        if following <= start:
            head.append(piece)
        elif position >= end:
            tail.append(piece)
        else:
            body.append(piece)
        position = following
    if not body:
        return strip
    selection_style = Visual.selection_style(widget).rich_style
    if selection_style is None:
        return strip
    painted = Strip(
        list(Segment.apply_style(Strip.join(body), None, selection_style)),
        sum(piece.cell_length for piece in body),
    )
    return Strip.join((*head, painted, *tail))


class LinkedRows(OpensLinks):
    """A widget that draws rendered rows: on its own background, opening the links clicked in them."""

    def on_background(self, strip: Strip) -> Strip:
        """A row as this widget draws it.

        Rendered rows carry text colours only. Textual fills a widget's
        background around its content, not under the rows it draws itself, so
        each row takes the widget's style here. A strip remembers the styles
        applied to it, so a repaint reuses the same drawn row.
        """
        return strip.apply_style(self.rich_style)

    def blank_row(self, width: int) -> Strip:
        return Strip.blank(width, self.rich_style)


class HorizontalRows(LinkedRows, ScrollView):
    """Prepared rows use Textual's horizontal viewport when code is unwrapped."""

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        raise NotImplementedError

    def get_content_width(self, container, viewport) -> int:
        return max((lines.content_width for lines in self.line_sets), default=0)

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
        lines = self.line_sets
        self.set_reactive(Widget.virtual_size, Size(
            max((item.content_width for item in lines), default=0),
            sum(item.height for item in lines),
        ))
        return super()._size_updated(size, virtual_size, container_size, layout)

    def on_background(self, strip: Strip) -> Strip:
        x = self.scroll_offset.x
        return super().on_background(strip.crop(x, x + self.scrollable_content_region.width))

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        rows = "\n".join("".join(segment.text for segment in row).rstrip()
                         for lines in self.line_sets for row in lines.rows)
        return selection.extract(rows), "\n"


def _plain_lines(text: str) -> list[str]:
    """A body's text as plain mode draws it: one string per source line, tabs expanded."""
    return [line.expandtabs(4) for line in text.splitlines() or [""]]


def _plain_spans(line: str, width: int) -> range:
    """Where plain mode breaks a line into rows: every `width` characters."""
    return range(0, max(1, len(line)), width)


class PatchLayout:
    """The chosen diff geometry, used by both measurement and painting."""

    def __init__(self, patch: Patch, width: int, settings: DiffSettings):
        self.patch, self.settings = patch, settings
        self.number_width = patch.number_width
        longest = max((cell_len(line.expandtabs(4)) for line in (*patch.before.values(), *patch.after.values())), default=0)
        self.split = settings.view.use_split(width, 2 * (longest + self.number_width + 4) + 3)
        self.pane_width = max(1, (width - 3) // 2 if self.split else width)
        self.prefix_width = (self.number_width + 1 if self.split else 2 * self.number_width + 2) + (2 if settings.annotations else 0)
        self.pane_width = settings.wrap.fitted_width(self.pane_width, longest + self.prefix_width)
        self.code_width = max(1, self.pane_width - self.prefix_width)

    @property
    def content_width(self) -> int:
        return self.pane_width * 2 + 3 if self.split else self.pane_width

    def breaks(self, text: str) -> list[int]:
        return divide_line(text, self.code_width, fold=True) if self.settings.wrap.enabled else []

    def cell_height(self, cell: PatchCell | None) -> int:
        return len(self.breaks(cell.text.expandtabs(4))) + 1 if cell is not None else 1

    @property
    def height(self) -> int:
        return len(self.patch.groups) + sum(
            max(self.cell_height(old), self.cell_height(new))
            for old, new in self.patch.rows(self.split)
        )


class SpanColumnLayout(Columns):
    """Shared span-cell layout for immediate, styled and widget presentations.

    Inherits Rich's complete-cell fitting and narrow wrapping. Original span
    links remain clickable even before styled worker output arrives.
    """

    def __init__(self, block: SpanColumns, theme: LineTheme | None = None):
        from rich.text import Text

        self.indent = block.indent
        self.color_system = theme.color_system if theme is not None else None
        cells = [Text.assemble(*((span.text, (theme.style(span.role) if theme is not None else Style.null())
                                 + link_style(span.link)) for span in cell)) for cell in block.cells]
        super().__init__(cells, padding=(0, 2))

    def rows(self, width: int) -> tuple[Row, ...]:
        from rich.console import Console
        from rich.padding import Padding

        console = Console(width=max(1, width), force_terminal=True, file=io.StringIO(),
                          color_system=self.color_system, legacy_windows=False)
        layout = Padding(self, (0, 0, 0, min(self.indent, max(0, width - 1))))
        return tuple(tuple(row) for row in console.render_lines(layout, console.options, pad=False))


class RichLineRenderer(MroDispatch):
    """Rows for each block type; plain mode skips Markdown for immediate drawing."""

    def __init__(self, theme: LineTheme, width: int, *, plain: bool = False):
        self.theme = theme
        self.width = width
        self.plain = plain
        self.output: list[Row] = []

    def rows(self, blocks: tuple[LineBlock, ...]) -> tuple[Row, ...]:
        self.output = []
        for block in blocks:
            self.dispatch_sync(block)
        return tuple(self.output)

    @handles(Patch)
    def patch(self, patch: Patch) -> None:
        """One numbered patch layout for live and saved tool output."""
        from rich.console import Console
        from rich.syntax import Syntax
        from rich.text import Text
        from toad.line_blocks import TextRole

        settings = self.theme.diff
        layout = PatchLayout(patch, self.width, settings)
        number_width, split = layout.number_width, layout.split
        pane_width, prefix_width, code_width = layout.pane_width, layout.prefix_width, layout.code_width
        console = Console(width=max(1, self.width), color_system=self.theme.color_system,
                          force_terminal=True, file=io.StringIO(), legacy_windows=False)

        def highlighted(lines, path):
            code = "\n".join(lines.values()).expandtabs(4)
            if self.plain:
                return {number: Text(text.expandtabs(4)) for number, text in lines.items()}
            syntax = Syntax(code, Syntax.guess_lexer(path, code), theme=self.theme.syntax.pygments_theme,
                            background_color="default")
            return dict(zip(lines, syntax.highlight(code).split("\n", allow_blank=True)))

        before = highlighted(patch.before, patch.before_path)
        after = highlighted(patch.after, patch.after_path)
        def paint(cell, source, old, new):
            if cell is None:
                return [Text(" " * pane_width)]
            style = self.theme.style(cell.role)
            tint = Style(bgcolor=style.bgcolor)
            if split:
                prefix = f"{cell.number:>{number_width}} "
            else:
                prefix = f"{old:>{number_width}} {new:>{number_width}} "
            if settings.annotations:
                prefix += cell.role.diff_marker + " "
            text = source[cell.number - 1].copy()
            chunks = text.divide(layout.breaks(text.plain))
            result = []
            for index, chunk in enumerate(chunks):
                chunk.truncate(code_width, overflow="crop", pad=True)
                chunk.stylize(tint)
                gutter = Text(prefix if index == 0 else " " * prefix_width,
                              style=style + tint if cell.role is not TextRole else self.theme.style(MutedRole))
                result.append(gutter + chunk)
            return result

        title = patch.after_path or patch.before_path or "Edit"
        if patch.before_path != patch.after_path:
            title = f"{patch.before_path} → {patch.after_path}"
        self.output.append((Segment(_fit(f"{title} (+{patch.additions}, −{patch.deletions})", self.width),
                                    self.theme.style(MutedRole)),))
        for group_index, group in enumerate(patch.row_groups(split)):
            if group_index:
                self.output.append((Segment("…", self.theme.style(MutedRole)),))
            for old, new in group:
                if split:
                    from itertools import zip_longest
                    left, right = paint(old, before, "", ""), paint(new, after, "", "")
                    blank = Text(" " * pane_width)
                    for a, b in zip_longest(left, right, fillvalue=blank):
                        self.output.append(tuple((a + Text(" │ ", style=self.theme.style(MutedRole)) + b).render(console)))
                else:
                    cell = old or new
                    source = before if old is not None else after
                    for row in paint(cell, source, str(old.number) if old else "", str(new.number) if new else ""):
                        self.output.append(tuple(row.render(console)))

    @handles(RichTextBody)
    def rich_text(self, block: RichTextBody) -> None:
        from rich.console import Console

        inner = _text_width(block, self.width)
        console = Console(width=inner, color_system=self.theme.color_system,
                          force_terminal=True, file=io.StringIO(), legacy_windows=False)
        rows = [tuple(row) for row in console.render_lines(
            block.content, console.options, style=self.theme.style(block.role), pad=False)]
        self._body_rows(block, rows)

    @handles(Divider)
    def divider(self, block: Divider) -> None:
        from toad.widgets.message_divider import MessageClock

        spans = block.spans
        if block.timestamp is not None:
            spans = (*spans, Span(f" · {MessageClock.recorded(block.timestamp).display()[0]}"))
        rule, bold = self.theme.style(block.role), Style(bold=True)
        title, room = [Segment(" ", rule)], max(0, self.width - 8)
        for span in spans:
            # A title longer than the rule ends in an ellipsis; what follows is not drawn.
            text = _fit(span.text, room)
            room -= cell_len(text)
            title.append(Segment(text, (rule if span.link is None else self.theme.style(span.role))
                                 + bold + link_style(span.link)))
            if room == 0:
                break
        title.append(Segment(" ", rule))
        length = sum(segment.cell_length for segment in title)
        left = max(0, (self.width - length) // 2)
        self.output.append((Segment("─" * left, rule), *title,
                            Segment("─" * max(0, self.width - left - length), rule)))

    @handles(Summary)
    def summary(self, block: Summary) -> None:
        room = max(0, self.width - sum(cell_len(span.text) for span in block.kept))
        row: list[Segment] = []
        for span in block.spans:
            text = _fit(span.text, room)
            room -= cell_len(text)
            row.append(Segment(text, self.theme.style(span.role) + link_style(span.link)))
        row.extend(Segment(span.text, self.theme.style(span.role) + link_style(span.link))
                   for span in block.kept)
        self.output.append(tuple(row))

    @handles(Spans)
    def spans(self, block: Spans) -> None:
        if self.plain:
            self.output.extend((Segment(line[start:start + self.width]),)
                               for line in _plain_lines(block.text)
                               for start in _plain_spans(line, self.width))
            return
        from rich.console import Console
        from rich.text import Text

        console = Console(width=self.width, color_system=self.theme.color_system,  # type: ignore[arg-type]
                          force_terminal=True, file=io.StringIO(), legacy_windows=False)
        text = Text.assemble(*((span.text, self.theme.style(span.role) + link_style(span.link))
                               for span in block.spans), tab_size=4)
        self.output.extend(tuple(line.render(console)) for line in text.wrap(console, self.width))

    @handles(SpanColumns)
    def columns(self, block: SpanColumns) -> None:
        self.output.extend(SpanColumnLayout(block, self.theme).rows(self.width))

    @handles(Gap)
    def gap(self, block: Gap) -> None:
        self.output.append(())

    @handles(Body)
    def body(self, block: Body) -> None:
        inner = _text_width(block, self.width)
        style = self.theme.style(block.role)
        if block.markdown and not self.plain:
            from rich.console import Console

            console = Console(width=inner, color_system=self.theme.color_system,  # type: ignore[arg-type]
                              force_terminal=True,
                              file=io.StringIO(), legacy_windows=False)
            rows = _clickable([tuple(line) for line in console.render_lines(
                _markdown(block.text), console.options.update(width=inner), style=style, pad=False)])
        else:
            rows = [(Segment(line[start:start + inner], style),)
                    for line in _plain_lines(block.text) for start in _plain_spans(line, inner)]
        self._body_rows(block, rows)

    def _body_rows(self, block: Body | RichTextBody, rows: list[Row]) -> None:
        if block.bar is not None:
            prefix = Segment("▌ ", self.theme.style(block.bar))
            rows = [(prefix, *row) for row in rows]
        self.output.extend(rows)


class PlainRowCount(MroDispatch):
    """How many rows plain mode draws blocks in at a width, without building them."""

    def __init__(self, width: int, theme: LineTheme | None = None):
        self.width = width
        self.theme = theme
        self.count = 0
        self.content_width = width

    def height(self, blocks: tuple[LineBlock, ...]) -> int:
        self.count = 0
        for block in blocks:
            self.dispatch_sync(block)
        return self.count

    @handles(Divider, Summary, Gap)
    def one_row(self, block: LineBlock) -> None:
        self.count += 1

    @handles(Body)
    def body(self, block: Body) -> None:
        inner = _text_width(block, self.width)
        self.count += sum(len(_plain_spans(line, inner)) for line in _plain_lines(block.text))

    @handles(Spans)
    def spans(self, block: Spans) -> None:
        self.count += sum(len(_plain_spans(line, self.width)) for line in _plain_lines(block.text))

    @handles(SpanColumns)
    def columns(self, block: SpanColumns) -> None:
        self.count += len(SpanColumnLayout(block, self.theme).rows(self.width))

    @handles(Patch)
    def patch(self, block: Patch) -> None:
        if self.theme is None:
            raise ValueError("Patch measurement requires its display settings")
        layout = PatchLayout(block, self.width, self.theme.diff)
        self.count += layout.height
        self.content_width = max(self.content_width, layout.content_width)

    @handles(RichTextBody)
    def rich_text(self, block: RichTextBody) -> None:
        inner = _text_width(block, self.width)
        self.count += sum(len(divide_line(line, inner)) + 1 for line in _plain_lines(block.content.plain))


class Lines:
    """Rows of text at one width (`width`, `rows`); strips are built once, on first draw.

    Each strip spans at least the width; unwrapped code can extend it. The
    strip keeps what painting computes (its terminal sequence) across
    repaints.
    """

    width: int
    rows: tuple[Row, ...]

    @property
    def height(self) -> int:
        return len(self.rows)

    @cached_property
    def content_width(self) -> int:
        return max((sum(segment.cell_length for segment in row) for row in self.rows), default=self.width)

    def strips_at(self, place: int) -> tuple[Strip, ...]:
        """The rows as strips, for the one owner (`link_place`) that draws them."""
        strips = self.__dict__.get("strips")
        if strips is None:
            width = self.width
            strips = self.__dict__["strips"] = tuple(
                Strip(row).extend_cell_length(width) for row in _each_link_apart(self.rows, place))
        return strips


@dataclass(frozen=True)
class PreparedLines(Lines):
    """Rows of one fragment at one width, rendered (styled) in a render worker."""

    width: int
    rows: tuple[Row, ...]


class PlainLines(Lines):
    """A fragment's plain rows at a width, drawn until its styled rows arrive.

    Layout reads only the height, which is counted without building a row;
    the rows are built when one of them is drawn.
    """

    def __init__(self, width: int, theme: LineTheme, blocks: tuple[LineBlock, ...]):
        self.width = width
        self.theme = theme
        self.blocks = blocks

    @cached_property
    def _measurement(self) -> PlainRowCount:
        measurement = PlainRowCount(self.width, self.theme)
        measurement.height(self.blocks)
        return measurement

    @property
    def height(self) -> int:
        return self._measurement.count

    @property
    def content_width(self) -> int:
        return self._measurement.content_width

    @cached_property
    def rows(self) -> tuple[Row, ...]:
        return RichLineRenderer(self.theme, self.width, plain=True).rows(self.blocks)


@dataclass(frozen=True)
class TranscriptLinesRenderTask(ReusableRenderTask[PreparedLines]):
    """Render a fragment's line blocks at a width in a render worker."""

    blocks: tuple[LineBlock, ...]
    width: int
    theme: LineTheme

    def execute(self) -> PreparedLines:
        return PreparedLines(self.width, RichLineRenderer(self.theme, self.width).rows(self.blocks))

    def accept_result(self, result: object) -> PreparedLines:
        if not isinstance(result, PreparedLines) or result.width != self.width:
            raise TypeError("Transcript line renderer returned rows for a different width")
        return result


@dataclass(frozen=True)
class TranscriptLinesBatchRenderTask(ReusableRenderTask[tuple[PreparedLines, ...]]):
    """Render several fragments' lines in one worker round trip.

    History lookahead prepares fragments in batches; one task per fragment
    cost a task, a process round trip and worker-thread hops each, flooding
    the UI loop with callbacks while scrolling.
    """

    items: tuple[TranscriptLinesRenderTask, ...]

    def execute(self) -> tuple[PreparedLines, ...]:
        return tuple(item.execute() for item in self.items)

    def accept_result(self, result: object) -> tuple[PreparedLines, ...]:
        if not isinstance(result, tuple) or len(result) != len(self.items):
            raise TypeError("Transcript batch renderer returned a different number of fragments")
        return tuple(item.accept_result(lines) for item, lines in zip(self.items, result))
