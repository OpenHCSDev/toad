"""The Rich/Textual frontend for transcript line blocks.

`toad.line_blocks` says what a fragment shows. This module decides how it looks
in Textual: a theme maps each role to a style, and a renderer turns each block
into rows. Styled rows are rendered in the render worker processes; until they
arrive a fragment draws plain rows, so a row is never blank.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import io

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

from agent_comms.mro_dispatch import MroDispatch, handles
from toad.line_blocks import (
    AgentRole, Body, Divider, Gap, IncomingRole, LineBlock, LineRole, MutedRole, NoticeRole,
    OutgoingRole, Summary, TextRole, ThinkingRole, UserRole,
)
from toad.render_backend import ReusableRenderTask

Row = tuple[Segment, ...]


@dataclass(frozen=True)
class LineTheme:
    """Styles for line roles, resolved once from the App's theme."""

    styles: tuple[tuple[type[LineRole], Style], ...]

    def style(self, role: type[LineRole]) -> Style:
        # A role without its own style uses its nearest parent's.
        table = dict(self.styles)
        for owner in role.__mro__:
            if owner in table:
                return table[owner]
        return Style()

    @classmethod
    def from_app(cls, app) -> LineTheme:
        from textual.color import Color

        theme = app.current_theme
        variables = app.theme_variables
        foreground = Color.parse(variables["foreground"])
        background = Color.parse(variables["background"])
        muted = background.blend(foreground, 0.6).rich_color

        def color(value: str | None) -> Style:
            return Style(color=(Color.parse(value) if value else foreground).rich_color)

        return cls((
            (TextRole, color(None)),
            # Textual's text-muted is the foreground at 60% over the background.
            (MutedRole, Style(color=muted)),
            (ThinkingRole, Style(color=muted, italic=True)),
            (UserRole, color(theme.primary)),
            (AgentRole, color(theme.secondary or theme.primary)),
            (IncomingRole, color(theme.accent)),
            (OutgoingRole, color(theme.success)),
            (NoticeRole, color(theme.warning)),
        ))


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


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
        self.output.append((Segment(_fit(block.text, self.width), self.theme.style(block.role)),))

    @handles(Gap)
    def gap(self, block: Gap) -> None:
        self.output.append(())

    @handles(Body)
    def body(self, block: Body) -> None:
        inset = 2 if block.bar is not None else 0
        inner = max(1, self.width - inset)
        style = self.theme.style(block.role)
        if block.markdown and not self.plain:
            from rich.console import Console
            from rich.markdown import Markdown

            console = Console(width=inner, color_system="truecolor", force_terminal=True,
                              file=io.StringIO(), legacy_windows=False)
            rows = [tuple(line) for line in console.render_lines(
                Markdown(block.text), console.options.update(width=inner), style=style, pad=False)]
        else:
            rows = []
            for line in block.text.splitlines() or [""]:
                line = line.expandtabs(4)
                for start in range(0, max(1, len(line)), inner):
                    rows.append((Segment(line[start:start + inner], style),))
        if block.bar is not None:
            prefix = Segment("▌ ", self.theme.style(block.bar))
            rows = [(prefix, *row) for row in rows]
        self.output.extend(rows)


@dataclass(frozen=True)
class PreparedLines:
    """Rows of one fragment at one width; strips are built once, on first draw."""

    width: int
    rows: tuple[Row, ...]

    @cached_property
    def strips(self) -> tuple[Strip, ...]:
        return tuple(Strip(row) for row in self.rows)


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
