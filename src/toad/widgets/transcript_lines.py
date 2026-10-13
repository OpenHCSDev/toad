"""The Rich/Textual frontend for transcript line blocks.

`toad.line_blocks` says what a fragment shows. This module decides how it looks
in Textual: a theme maps each role's colour to a style, and a renderer turns each block
into rows. Styled rows are rendered in the render worker processes; until they
arrive a fragment draws plain rows, so a row is never blank.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
import io
from itertools import count
from threading import local

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.visual import Visual
from textual.widget import Widget

from agent_comms.mro_dispatch import MroDispatch, handles
from ui_theme.scheme import MutedColour, ThemeColour
from toad.line_blocks import (
    Body, Divider, Gap, LineBlock, LineLink, LineRole, OpenHistoricalTarget, OpenTarget, OpenUrl, Span, Spans,
    Summary,
)
from toad.core.input_events import SelectHistoricalIdentity, SelectTarget
from toad.menus import MenuItem
from toad.message_rows import MessageRow
from toad.core_event_carrier import CoreEventReceiver
from toad.navigation_target import linked_target
from toad.render_backend import ReusableRenderTask

Row = tuple[Segment, ...]


@dataclass(frozen=True)
class LineTheme:
    """Rich styles for the theme colours, resolved once per theme from its CSS variables,
    and the host terminal's colour system (Rich's name for the colour depth)."""

    colours: tuple[tuple[type[ThemeColour], Style], ...]
    color_system: str

    def style(self, role: type[LineRole]) -> Style:
        for colour, style in self.colours:
            if colour is role.colour:
                return style + Style(italic=role.italic or None, bold=role.bold or None,
                                     underline=role.underline or None)
        raise KeyError(f"{role.__name__} asks for {role.colour.__name__}, which the theme lacks")

    def with_colour(self, colour: type[ThemeColour], style: Style) -> LineTheme:
        """This theme with one colour drawn another way, as a fade draws it part of the way through."""
        return LineTheme(((colour, style), *self.colours), self.color_system)

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


def _click(link: LineLink | None) -> Style:
    """The style that makes text run a link's action when clicked."""
    return Style.null() if link is None else Style(
        underline=link.underlined or None, meta={"@click": link.click})


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _text_width(block: Body, width: int) -> int:
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
    painted = Strip(
        list(Segment.apply_style(Strip.join(body), None, Visual.selection_style(widget))),
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


def _plain_lines(text: str) -> list[str]:
    """A body's text as plain mode draws it: one string per source line, tabs expanded."""
    return [line.expandtabs(4) for line in text.splitlines() or [""]]


def _plain_spans(line: str, width: int) -> range:
    """Where plain mode breaks a line into rows: every `width` characters."""
    return range(0, max(1, len(line)), width)


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
            room -= len(text)
            title.append(Segment(text, (rule if span.link is None else self.theme.style(span.role))
                                 + bold + _click(span.link)))
            if text != span.text:
                break
        title.append(Segment(" ", rule))
        length = sum(len(segment.text) for segment in title)
        left = max(0, (self.width - length) // 2)
        self.output.append((Segment("─" * left, rule), *title,
                            Segment("─" * max(0, self.width - left - length), rule)))

    @handles(Summary)
    def summary(self, block: Summary) -> None:
        self.output.append((Segment(_fit(block.text, self.width),
                                    self.theme.style(block.role) + _click(block.link)),))

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
        text = Text.assemble(*((span.text, self.theme.style(span.role) + _click(span.link))
                               for span in block.spans), tab_size=4)
        self.output.extend(tuple(line.render(console)) for line in text.wrap(console, self.width))

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
        if block.bar is not None:
            prefix = Segment("▌ ", self.theme.style(block.bar))
            rows = [(prefix, *row) for row in rows]
        self.output.extend(rows)


class PlainRowCount(MroDispatch):
    """How many rows plain mode draws blocks in at a width, without building them."""

    def __init__(self, width: int):
        self.width = width
        self.count = 0

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


class Lines:
    """Rows of text at one width (`width`, `rows`); strips are built once, on first draw.

    Each strip spans exactly the width, so a page draws it as it is and the
    strip keeps what painting it computes (its terminal sequence) across
    repaints.
    """

    width: int
    rows: tuple[Row, ...]

    @property
    def height(self) -> int:
        return len(self.rows)

    def strips_at(self, place: int) -> tuple[Strip, ...]:
        """The rows as strips, for the one owner (`link_place`) that draws them."""
        strips = self.__dict__.get("strips")
        if strips is None:
            width = self.width
            strips = self.__dict__["strips"] = tuple(
                Strip(row).extend_cell_length(width).crop(0, width) for row in _each_link_apart(self.rows, place))
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
    def height(self) -> int:
        return PlainRowCount(self.width).height(self.blocks)

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
