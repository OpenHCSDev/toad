"""The shared line renderer: workers style source; native views wrap it at their width.

`toad.line_blocks` owns content. Prepared source survives resizing, while each
viewport owns its measured rows. Unprepared source retains its initial preview.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import cached_property
import io
from itertools import count
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.textual_colours import PaletteState, TextualColours

from rich.cells import cell_len, set_cell_size
from rich.columns import Columns
from rich.console import Console
from rich.containers import Renderables
from rich.syntax import Syntax
from rich.text import Text
from rich._wrap import divide_line
from rich.segment import Segment
from rich.style import Style
from textual._paint_state import PaintState
from textual.strip import Strip
from textual.visual import Visual
from textual.widget import Widget
from textual.scroll_view import ScrollView
from textual.geometry import Size
from textual.selection import Selection
from toad.rich_preparation import RichTextBody
from toad.project_link import ProjectLink

from agent_comms.mro_dispatch import MroDispatch, handles
from ui_theme.scheme import ForegroundColour, MutedColour, ThemeColour
from toad.line_blocks import (
    Body, Divider, Gap, LineBlock, LineLink, LineRole, OpenHistoricalTarget, OpenReference, OpenTarget, Span, Spans, SpanColumns,
    Summary, MutedRole, TextRole,
)
from toad.core.input_events import SelectHistoricalIdentity, SelectTarget
from toad.menus import MenuItem
from toad.message_rows import MessageRow, WireBody
from toad.markdown_links import LinkContext
from toad.markdown_preparation import MarkdownStyleConsole
from agent_comms.display_references import ChannelDisplayReference, HistoricalDisplayReference, ThreadDisplayReference
from toad.core_event_carrier import CoreEventReceiver
from toad.navigation_target import NavigationTarget
from toad.render_backend import ReusableRenderTask
from toad.patch import Patch
from toad.preferences import DiffSettings
from toad.rich_preparation import SyntaxPalette

Row = tuple[Segment, ...]


@dataclass(frozen=True)
class LineTheme:
    """Fully resolved role styles for one theme and terminal colour system."""

    styles: Mapping[type[LineRole], Style]
    color_system: str
    diff: DiffSettings = field(default_factory=DiffSettings)
    syntax: SyntaxPalette = SyntaxPalette(False, True)

    def style(self, role: type[LineRole]) -> Style:
        return self.styles[role]

    @staticmethod
    def _style(role: type[LineRole], style: Style, palette: PaletteState) -> Style:
        if role.background_tint:
            style = palette.tint(style, role.background_tint)
        return style + Style(italic=role.italic or None, bold=role.bold or None,
                             underline=role.underline or None)

    def with_colour(self, colour: type[ThemeColour], style: Style, palette: PaletteState) -> LineTheme:
        """This theme with one colour drawn another way, as a fade draws it part of the way through."""
        return replace(self, styles={role: self._style(role, style, palette)
                                     if role.colour is colour else held for role, held in self.styles.items()})

    @classmethod
    def of(cls, colours: TextualColours) -> LineTheme:
        # Native ANSI text retains its distinct dim attribute rather than a palette guess.
        muted = (Style(dim=True) if colours.colour(ForegroundColour).ansi is not None
                 else Style(color=colours.colour(MutedColour).rich_color))
        return cls({role: cls._style(role, muted if role.colour is MutedColour
                                    else Style(color=colours.colour(role.colour).rich_color),
                                    colours.schemes[colours.app.theme].palette) for role in LineRole.members_with(LineRole)},
                   colours.depth.name, diff=colours.app.settings.diff, syntax=SyntaxPalette.of(colours.app))


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
        return Segment(segment.text, style + link_style(style.link.target), segment.control)

    return [tuple(map(linked, row)) for row in rows]


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
        self.publish_core(SelectTarget(NavigationTarget.named(link.target)))

    @handles(OpenHistoricalTarget)
    def open_historical_target(self, link: OpenHistoricalTarget) -> None:
        self.publish_core(SelectHistoricalIdentity(link.target, link.source))

    @handles(OpenReference)
    def open_reference(self, link: OpenReference) -> None:
        source = self.app.coordination_access.reference_context(link.reference.root)
        if not link.reference.current_in(source):
            self.notify(source.description or "This reference belongs to a replaced source.", severity="warning")
            return
        self.dispatch_sync(link.reference)

    @handles(ThreadDisplayReference, ChannelDisplayReference)
    def open_current_reference(self, reference) -> None:
        self.open_target(OpenTarget(reference.name))

    @handles(HistoricalDisplayReference)
    def open_recorded_reference(self, reference) -> None:
        self.open_historical_target(OpenHistoricalTarget(reference.name, reference.source))

    @handles(ProjectLink)
    def open_project_link(self, link: ProjectLink) -> None:
        self.run_worker(link.preview(self), group="open-link")

    def action_link(self, href: str) -> None:
        """Decode Markdown's transport once, then use the ordinary typed actions."""
        self.action_open(LineLink.from_href(href))


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

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        raise NotImplementedError

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        rows = "\n".join("".join(segment.text for segment in row).rstrip()
                         for lines in self.line_sets for row in lines.rows)
        return selection.extract(rows), "\n"

    def on_background(self, strip: Strip, paint: PaintState, y: int, x: int = 0) -> Strip:
        """A row as this widget draws it.

        Rendered rows carry text colours only. Textual fills a widget's
        background around its content, not under the rows it draws itself, so
        each row takes the widget's style here. A strip remembers the styles
        applied to it, so a repaint reuses the same drawn row.
        """
        return strip.apply_style(paint.rich_style).apply_offsets(x, y)

    def blank_row(self, width: int, paint: PaintState) -> Strip:
        return Strip.blank(width, paint.rich_style)


class HorizontalRows(LinkedRows, ScrollView):
    """Prepared rows use Textual's horizontal viewport when code is unwrapped."""

    def get_content_width(self, container, viewport) -> int:
        return max((lines.content_width for lines in self.line_sets), default=0)

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
        lines = self.line_sets
        self.set_reactive(Widget.virtual_size, Size(
            max((item.content_width for item in lines), default=0),
            sum(item.height for item in lines),
        ))
        return super()._size_updated(size, virtual_size, container_size, layout)

    def on_background(self, strip: Strip, paint: PaintState, y: int, x: int = 0) -> Strip:
        start = self.scroll_offset.x
        x += len(strip.crop(0, start).text) if start else 0
        return super().on_background(strip.crop(start, start + self.scrollable_content_region.width), paint, y, x)


def _plain_lines(text: str) -> list[str]:
    """A body's text as plain mode draws it: one string per source line, tabs expanded."""
    return [line.expandtabs(4) for line in text.splitlines() or [""]]


def _plain_spans(line: str, width: int) -> range:
    """Where plain mode breaks a line into rows: every `width` characters."""
    return range(0, max(1, len(line)), width)


class PatchLayout:
    """Diff geometry used by the native row painter."""

    def __init__(self, patch: Patch, width: int, settings: DiffSettings):
        self.patch, self.settings = patch, settings
        self.number_width = patch.number_width
        longest = max((cell_len(line.expandtabs(4)) for line in (*patch.before.values(), *patch.after.values())), default=0)
        self.split = settings.view.use_split(width, 2 * (longest + self.number_width + 4) + 3)
        self.pane_width = max(1, (width - 3) // 2 if self.split else width)
        self.prefix_width = (self.number_width + 1 if self.split else 2 * self.number_width + 2) + (2 if settings.annotations else 0)
        self.pane_width = settings.wrap.fitted_width(self.pane_width, longest + self.prefix_width)
        self.code_width = max(1, self.pane_width - self.prefix_width)

    def breaks(self, text: str) -> list[int]:
        return divide_line(text, self.code_width, fold=True) if self.settings.wrap.enabled else []


class Lines:
    """Rows at one width; each drawing owner builds its own marked strips."""

    width: int
    rows: tuple[Row, ...]

    @property
    def height(self) -> int:
        return len(self.rows)

    @cached_property
    def content_width(self) -> int:
        return max((sum(segment.cell_length for segment in row) for row in self.rows), default=self.width)

    def strips_at(self, place: int) -> tuple[Strip, ...]:
        """Link placement decorates this view's paint, never shared preparation."""
        strips = self.__dict__.get("strips")
        if strips is None:
            width = self.width
            strips = self.__dict__["strips"] = tuple(
                Strip(row).extend_cell_length(width) for row in _each_link_apart(self.rows, place))
        return strips


@dataclass(frozen=True)
class PreparedLines(Lines, LineBlock):
    """Immutable rows can also supply an already laid-out part of a fragment."""

    width: int
    rows: tuple[Row, ...]

    @property
    def retained_bytes(self) -> int:
        return 64 + sum(64 + sum(64 + 4 * len(segment.text) for segment in row)
                        for row in self.rows)

    def prepared_rows(self, width, draw) -> PreparedLines:
        if width != self.width:
            raise ValueError("Prepared rows belong to a different width")
        return self


class PreparedBlock(LineBlock):
    """A prepared source owns one immutable row snapshot; views borrow it."""

    _rows: PreparedLines = PreparedLines(width=-1, rows=())

    def prepared_rows(self, width, draw) -> PreparedLines:
        rows = self._rows
        if rows.width != width:
            self._rows = rows = draw(self)
        return rows


class SpanColumnLayout(Columns, PreparedBlock):
    """Shared span-cell layout for immediate, styled and widget presentations.

    Inherits Rich's complete-cell fitting and narrow wrapping. Original span
    links remain clickable even before styled worker output arrives.
    """

    def __init__(self, block: SpanColumns, theme: LineTheme | None = None):
        self.indent = block.indent
        cells = [Text.assemble(*((span.text, (theme.style(span.role) if theme is not None else Style.null())
                                 + link_style(span.link)) for span in cell)) for cell in block.cells]
        super().__init__(cells, padding=(0, 2))

    def rows(self, console: Console) -> tuple[Row, ...]:
        from rich.padding import Padding

        layout = Padding(self, (0, 0, 0, min(self.indent, max(0, console.width - 1))))
        return tuple(tuple(row) for row in console.render_lines(layout, console.options, pad=False))


@dataclass
class StyledBody(PreparedBlock):
    source: Body | RichTextBody
    content: tuple

    @property
    def selection_text(self) -> str:
        return self.source.selection_text


@dataclass(slots=True)
class StyledPatch(Patch, PreparedBlock):
    before_text: dict[int, Text] = field()
    after_text: dict[int, Text] = field()


class RichLineRenderer(MroDispatch):
    """Paint each primitive through its most-specific declared renderer."""

    def __init__(self, theme: LineTheme, width: int = 1):
        self.theme, self.width = theme, max(1, width)
        self.output: list[Row] = []

    @cached_property
    def console(self) -> Console:
        return Console(width=self.width, color_system=self.theme.color_system,
                       force_terminal=True, file=io.StringIO(), legacy_windows=False)

    def at_width(self, width: int) -> RichLineRenderer:
        self.width = self.console.width = max(1, width)
        return self

    def __call__(self, block: LineBlock) -> PreparedLines:
        return PreparedLines(self.width, self.rows((block,)))

    def rows(self, blocks: tuple[LineBlock, ...]) -> tuple[Row, ...]:
        self.output = []
        for block in blocks:
            next(self.handlers_for(block))(block)
        return tuple(self.output)

    @handles(Patch)
    def patch(self, patch: Patch) -> None:
        before, after = patch.before_text, patch.after_text
        settings = self.theme.diff
        layout = PatchLayout(patch, self.width, settings)
        number_width, split = layout.number_width, layout.split
        pane_width, prefix_width, code_width = layout.pane_width, layout.prefix_width, layout.code_width
        console = self.console
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
        inner = _text_width(block, self.width)
        console = self.console
        rows = [tuple(row) for row in console.render_lines(
            block.content, console.options.update(width=inner), style=self.theme.style(block.role), pad=False)]
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
        self.output.extend((Segment(line[start:start + self.width]),)
                           for line in _plain_lines(block.text)
                           for start in _plain_spans(line, self.width))

    @handles(PreparedLines)
    def prepared(self, block: PreparedLines) -> None:
        self.output.extend(block.prepared_rows(self.width, self).rows)

    @handles(Gap)
    def gap(self, block: Gap) -> None:
        self.output.append(())

    @handles(WireBody)
    def wire_body(self, block: WireBody) -> None:
        self.body(Body(block.text, bar=block.bar))

    @handles(SpanColumns)
    def columns(self, block: SpanColumns) -> None:
        self.prepared_columns(SpanColumnLayout(block, self.theme))

    @handles(SpanColumnLayout)
    def prepared_columns(self, block: SpanColumnLayout) -> None:
        self.output.extend(block.rows(self.console))

    @handles(StyledBody)
    def styled_body(self, block: StyledBody) -> None:
        source = block.source
        rows = _clickable([tuple(line) for line in self.console.render_lines(
            Renderables(block.content), self.console.options.update(width=_text_width(source, self.width)),
            style=self.theme.style(source.role), pad=False)])
        self._body_rows(source, rows)

    @handles(Body)
    def body(self, block: Body) -> None:
        inner = _text_width(block, self.width)
        style = self.theme.style(block.role)
        self._body_rows(block, [(Segment(line[start:start + inner], style),)
                               for line in _plain_lines(block.text) for start in _plain_spans(line, inner)])

    def _body_rows(self, block: Body | RichTextBody, rows: list[Row]) -> None:
        if block.bar is not None:
            prefix = Segment("▌ ", self.theme.style(block.bar))
            rows = [(prefix, *row) for row in rows]
        self.output.extend(rows)


@dataclass(frozen=True)
class LinePreparation:
    """Source styling and palette, independent of every viewport's width."""

    blocks: tuple[LineBlock, ...]
    theme: LineTheme

    @property
    def retained_bytes(self) -> int:
        return 256 + sum(block.retained_bytes for block in self.blocks)

    def wrap(self, width: int, renderer: RichLineRenderer) -> BlockLines:
        return BlockLines(width, self, renderer)


class BlockLines(Lines):
    """A viewport retains immutable references to block-owned row snapshots."""

    def __init__(self, width: int, preparation: LinePreparation, renderer: RichLineRenderer):
        self.width, self.preparation, self.renderer = width, preparation, renderer

    def rewrap(self, width: int) -> BlockLines:
        return self if self.width == width else self.preparation.wrap(width, self.renderer)

    @cached_property
    def prepared_blocks(self) -> tuple[PreparedLines, ...]:
        draw = self.renderer.at_width(self.width)
        return tuple(block.prepared_rows(self.width, draw) for block in self.preparation.blocks)

    @cached_property
    def height(self) -> int:
        return sum(block.height for block in self.prepared_blocks)

    @property
    def rows(self) -> tuple[Row, ...]:
        return tuple(row for block in self.prepared_blocks for row in block.rows)


class PlainLines(BlockLines):
    """Unstyled source measurement before its first worker result arrives."""

    def __init__(self, width: int, renderer: RichLineRenderer, blocks: tuple[LineBlock, ...]):
        super().__init__(width, LinePreparation(blocks, renderer.theme), renderer)

class RowAcquisition(ABC):
    """The source witness and rows acquired by one fragment."""

    @property
    @abstractmethod
    def preparation(self) -> LinePreparation | NoRows: ...

    @abstractmethod
    def for_view(self, width: int, theme: LineTheme) -> BlockLines | None: ...

    @abstractmethod
    def retains(self, lines: BlockLines, theme: LineTheme) -> bool: ...

    def plain(self, width: int, renderer: RichLineRenderer, blocks: tuple[LineBlock, ...]) -> AcquiredRows:
        lines = PlainLines(width, renderer, blocks)
        return PlainRows(lines.preparation, lines)


class NoRows(RowAcquisition):
    retained_bytes = 0

    @property
    def preparation(self) -> NoRows:
        return self

    def for_view(self, width, theme):
        return None

    def retains(self, lines, theme):
        return False


@dataclass
class AcquiredRows(RowAcquisition):
    source: LinePreparation
    lines: BlockLines

    @property
    def preparation(self) -> LinePreparation:
        return self.lines.preparation

    def for_view(self, width, theme):
        if self.source.theme is not theme:
            return None
        self.lines = self.lines.rewrap(width)
        return self.lines

    def retains(self, lines, theme):
        return self.source.theme is theme and self.lines.preparation is lines.preparation

    def plain(self, width, renderer, blocks):
        if self.source.theme is renderer.theme:
            self.lines = self.lines.rewrap(width)
            return self
        return super().plain(width, renderer, blocks)


class PlainRows(AcquiredRows):
    def retains(self, lines, theme):
        return self.source.theme is theme and self.lines.preparation.blocks is lines.preparation.blocks


@dataclass(frozen=True)
class TranscriptLinesRenderTask(MroDispatch, ReusableRenderTask[LinePreparation]):
    def result_size(self, result: LinePreparation) -> int:
        return result.retained_bytes

    """Style one source once; width never enters the worker contract."""

    preparation: LinePreparation
    context: LinkContext

    @property
    def blocks(self) -> tuple[LineBlock, ...]:
        """The original source witness, never the normalized drawing blocks."""
        return self.preparation.blocks

    def current_for(self, view) -> bool:
        return self.context.current_for(view) and self.preparation.theme is view.app.colours.line_theme

    def hold(self, view, fragment, lines) -> bool:
        return self.current_for(view) and fragment.hold_lines(self, lines.wrap(view.line_width, view.app.colours.line_renderer))

    @staticmethod
    def show(view, fragment, shown, rendered) -> None:
        """Apply the requested state, retaining rows only through their render request."""
        fragment.show(shown)
        if rendered is not None:
            request, lines = rendered
            if request.current_for(view):
                fragment.line_blocks = request.blocks
                fragment.hold_lines(request, lines.wrap(view.line_width, view.app.colours.line_renderer))

    def execute(self) -> LinePreparation:
        return LinePreparation(tuple(next(self.handlers_for(block))(block) for block in self.blocks), self.preparation.theme)

    @handles(LineBlock)
    def unchanged(self, block: LineBlock) -> LineBlock:
        return block

    @handles(Body)
    def body(self, block: Body) -> LineBlock:
        return block.prepare(self.markdown)

    def markdown(self, block: Body) -> StyledBody:
        console = MarkdownStyleConsole(force_terminal=True, file=io.StringIO(),
                                       color_system=self.preparation.theme.color_system)
        return StyledBody(block, console.prepare(block.text, self.context))

    @handles(WireBody)
    def wire_body(self, block: WireBody) -> LineBlock:
        prepared = block.prepare(self.context.for_source(block.row.message.history_source))
        return next(self.handlers_for(prepared))(prepared)

    @handles(RichTextBody)
    def rich_text(self, block: RichTextBody) -> StyledBody:
        return StyledBody(block, (block.content,))

    @handles(SpanColumns)
    def columns(self, block: SpanColumns) -> SpanColumnLayout:
        return SpanColumnLayout(block, self.preparation.theme)

    @handles(Spans)
    def spans(self, block: Spans) -> StyledBody:
        text = Text.assemble(*((span.text, self.preparation.theme.style(span.role) + link_style(span.link))
                               for span in block.spans), tab_size=4)
        return self.rich_text(RichTextBody(text, role=TextRole, bar=None))

    @handles(Patch)
    def patch(self, block: Patch) -> StyledPatch:
        def highlight(lines, path):
            code = "\n".join(lines.values()).expandtabs(4)
            syntax = Syntax(code, Syntax.guess_lexer(path, code),
                            theme=self.preparation.theme.syntax.pygments_theme, background_color="default")
            return dict(zip(lines, syntax.highlight(code).split("\n", allow_blank=True)))
        return StyledPatch(block.before_path, block.after_path, block.before, block.after, block.groups,
                           highlight(block.before, block.before_path), highlight(block.after, block.after_path))


@dataclass(frozen=True)
class TranscriptLinesBatchRenderTask(ReusableRenderTask[tuple[LinePreparation, ...]]):
    def result_size(self, result: tuple[LinePreparation, ...]) -> int:
        return 64 + sum(preparation.retained_bytes for preparation in result)

    """Style several newly acquired sources in one worker round trip."""

    items: tuple[TranscriptLinesRenderTask, ...]

    @classmethod
    async def render_for(cls, view, preparations):
        """One captured reference source for a batch; requests own result publication."""
        preparations = tuple(preparations)
        if not preparations:
            return ()
        context = await LinkContext.acquire(view)
        items = tuple(TranscriptLinesRenderTask(preparation, context) for preparation in preparations)
        lines = await view.app.render_processes.submit(cls(items))
        return tuple(zip(items, lines, strict=True))

    def execute(self) -> tuple[LinePreparation, ...]:
        return tuple(item.execute() for item in self.items)
