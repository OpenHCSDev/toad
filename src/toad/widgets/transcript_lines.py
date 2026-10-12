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

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

from agent_comms.mro_dispatch import MroDispatch, handles
from ui_theme.scheme import MutedColour, ThemeColour
from toad.line_blocks import Body, Divider, Gap, LineBlock, LineLink, LineRole, Spans, Summary
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
    return Style.null() if link is None else Style(meta={"@click": link.click})


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _text_width(block: Body, width: int) -> int:
    """The cells a body's text wraps at: the width less its bar."""
    return max(1, width - (2 if block.bar is not None else 0))


def _clickable(rows: list[Row]) -> list[Row]:
    """Give each Markdown link the click action that hovers and opens it.

    Rich marks a link's cells with its address only. Textual highlights and
    activates cells that carry a click action and share a link identity, so
    every cell of one link gets one action style.
    """
    actions: dict[str, Style] = {}

    def linked(segment: Segment) -> Segment:
        style = segment.style
        if style is None or not style.link:
            return segment
        action = actions.get(style.link_id)
        if action is None:
            action = actions[style.link_id] = Style.from_meta({"@click": f"link({style.link!r})"})
        return Segment(segment.text, style + action, segment.control)

    return [tuple(map(linked, row)) for row in rows]


class LinkedRows:
    """A widget that draws rendered rows opens the links clicked in them."""

    async def action_link(self, href: str) -> None:
        from toad.project_path_owner import ProjectPathOwner

        await ProjectPathOwner.link_from(self, href).preview(self)


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

        label = block.label
        if block.timestamp is not None:
            label = f"{label} · {MessageClock.recorded(block.timestamp).display()[0]}"
        style = self.theme.style(block.role)
        label = f" {_fit(label, max(0, self.width - 8))} "
        left = max(0, (self.width - len(label)) // 2)
        right = max(0, self.width - left - len(label))
        self.output.append((Segment("─" * left, style), Segment(label, style + Style(bold=True)),
                            Segment("─" * right, style)))

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
            from rich.markdown import Markdown

            console = Console(width=inner, color_system=self.theme.color_system,  # type: ignore[arg-type]
                              force_terminal=True,
                              file=io.StringIO(), legacy_windows=False)
            rows = _clickable([tuple(line) for line in console.render_lines(
                Markdown(block.text), console.options.update(width=inner), style=style, pad=False)])
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

    @cached_property
    def strips(self) -> tuple[Strip, ...]:
        width = self.width
        return tuple(Strip(row).extend_cell_length(width).crop(0, width) for row in self.rows)


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
