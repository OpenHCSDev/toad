"""A full-width, timestamped separator owned by one displayed message."""

from __future__ import annotations

from dataclasses import replace

from agent_comms.ui_model.message_category import MessageCategory
from rich.style import Style
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual._paint_state import PaintState
from textual.geometry import Size
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget
from ui_theme.effects import NEW_MESSAGE, Mix

from toad.block_content import BlockContent
from toad.block_navigation import CategorizedBlock, ConversationBlock
from toad.frame_presentation import Animated, EffectInContent
from toad.client.line_blocks import Divider, Gap, LineBlock
from toad.native_style import (
    AutoHeight,
    FillWidth,
    ScreenOverlay,
    SpacedAbove,
    StartsHidden,
)
from toad.message_rows import LiveMessageClock, MessageClock, MessageRow
from toad.widgets.committed_presentation import block_claim
from toad.commit_claims import CommitParticipant
from toad.widgets.linked_rows import LinkedRows, MessageRowBlock
from toad.widgets.transcript_lines import (
    BlockLines,
    LineTheme,
    NoRows,
    RowAcquisition,
    RichLineRenderer,
)
from toad.client.history_changes import HeaderPin, PinsMessageHeader
from toad.client.agent_activity import AgentActivityPresentation
from textual.events import Click, Mount
from textual import on



class LineBlockRow(FillWidth, AutoHeight, LinkedRows, Widget):
    """One semantic line block, drawn exactly as transcript history draws it."""


    def __init__(self, block: LineBlock) -> None:
        super().__init__()
        self.block = block
        self._lines: RowAcquisition = NoRows()

    @property
    def line_theme(self) -> LineTheme:
        return self.app.colours.line_theme

    def update_block(self, block: LineBlock) -> None:
        if block != self.block:
            self.block, self._lines = block, NoRows()
            self.refresh(layout=True)

    @property
    def line_sets(self) -> tuple[BlockLines, ...]:
        return (self.prepared_lines(self.size.width),)

    @property
    def drawn_blocks(self) -> tuple[LineBlock, ...]:
        """The blocks this row draws, top to bottom: its one block."""
        return (self.block,)

    def prepared_lines(self, width: int) -> BlockLines:
        measured = self._lines.plain(
            width, RichLineRenderer(self.line_theme, width), self.drawn_blocks
        )
        self._lines = measured
        return measured.lines

    def render_line(self, y: int, paint: PaintState) -> Strip:
        width = self.size.width
        if not width:
            return self.blank_row(width, paint)
        lines = self.prepared_lines(width)
        if y >= lines.height:
            return self.blank_row(width, paint)
        return self.on_background(lines.strips_at(self.link_place)[y], paint, y)

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return self.prepared_lines(width).height


class ConversationLineBlock(BlockContent, LineBlockRow):
    """A line block in the conversation: navigable and selectable like any block."""

    def get_selection(self, selection: Selection) -> tuple[str, str]:
        return selection.extract(self.block.selection_text), "\n"


class StickyHeader(HeaderPin, StartsHidden, ScreenOverlay, LineBlockRow):
    """`HeaderPin` as line blocks docked over the window's top row, drawn as the flow draws the
    messages' own header blocks. A click on a stacked header opens its message."""

    ALLOW_SELECT = False

    def __init__(self, window: PinsMessageHeader) -> None:
        super().__init__(Gap())
        self.window = window
        self.headers: tuple[LineBlock, ...] = ()

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.dock = "top"
        self.styles.layer = "float"

    @property
    def drawn_blocks(self) -> tuple[LineBlock, ...]:
        return self.headers

    def draw_pinned(self, headers: tuple[Divider, ...], x: int, width: int) -> None:
        if headers != self.headers:
            self.headers, self._lines = headers, NoRows()
            self.refresh(layout=True)
        if self.styles.width is None or self.styles.width.value != width:
            self.styles.width = width
        if self.styles.offset.x.value != x:
            self.styles.offset = (x, 0)

    @on(Click)
    def open_header(self, event: Click) -> None:
        """The header under the click opens its message, as a tap on Qt's pin does."""
        span = self.prepared_lines(self.size.width).block_span(lambda span: span.contains(event.y))
        if span.placed_by(lambda span: self.window.open_pinned(span.index), lambda: False):
            event.stop()

    def show_pin(self, shown: bool) -> None:
        self.display = shown


class MessageDivider(EffectInContent, SpacedAbove, Animated[Mix], ConversationLineBlock):
    """The rule above a live message: the same `Divider` block saved history draws.

    A message that has just arrived fades in from the accent colour.
    """

    block: Divider


    def __init__(self, block: Divider, *, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__(replace(block, timestamp=clock.event_time))
        self.fresh = clock.fresh
        self.tooltip = clock.display()[1]

    @property
    def line_theme(self) -> LineTheme:
        colours = self.app.colours
        theme = colours.line_theme
        mix = self.effect_frame(NEW_MESSAGE.ending_at(self.block.role.colour))
        colour = colours.mixed(mix.start, mix.end, mix.amount)
        return theme.with_colour(self.block.role.colour, Style(color=colour.rich_color),
                                 colours.schemes[self.app.theme].palette)

    @on(Mount)
    def on_mount(self) -> None:
        if self.fresh:
            # Once: a divider moved to another parent is not a new message.
            self.fresh = False
            self.run_effect(NEW_MESSAGE.ending_at(self.block.role.colour))


class MessageRowDivider(MessageRowBlock, MessageDivider):
    """The rule above a live bus message: the cursor's menu on it opens the sender or the destination."""

    def __init__(self, row: MessageRow, *, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__(row.header, clock=clock)
        self.message_row = row


class AgentActivityDivider(ConversationBlock, CommitParticipant, CategorizedBlock, ConversationLineBlock):
    """The shared activity-group row, filtered with the activity that follows it."""

    ALLOW_SELECT = False

    def __init__(self, category: type[MessageCategory], source: Widget) -> None:

        super().__init__(AgentActivityPresentation.group[0])
        self._category = category
        self.source = source

    @property
    def commit_claim(self):
        return block_claim(self.source)

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._category
