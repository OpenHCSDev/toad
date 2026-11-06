"""A full-width, timestamped separator owned by one displayed message."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

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
from toad.line_blocks import Divider, Gap, LineBlock
from toad.native_style import (
    AutoHeight,
    FillWidth,
    ScreenOverlay,
    SpacedAbove,
    StartsHidden,
)
from toad.message_rows import LiveMessageClock, MessageClock, MessageRow
from toad.widgets.committed_presentation import CommitParticipant, block_claim
from toad.widgets.linked_rows import LinkedRows, MessageRowBlock
from toad.widgets.transcript_lines import (
    BlockLines,
    LineTheme,
    NoRows,
    RowAcquisition,
    RichLineRenderer,
)

if TYPE_CHECKING:
    from toad.widgets.history_anchor import PinnedHeader


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

    def prepared_lines(self, width: int) -> BlockLines:
        measured = self._lines.plain(
            width, RichLineRenderer(self.line_theme, width), (self.block,)
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


class StickyHeader(StartsHidden, ScreenOverlay, LineBlockRow):
    """The header of the message under the window's top row, pinned there while its own row
    is scrolled above, so the reader of a long message still sees who sent it to whom, and when.

    It is the message's own header block drawn the same way; it keeps no copy of the message.
    """

    ALLOW_SELECT = False

    def __init__(self) -> None:
        super().__init__(Gap())

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.dock = "top"
        self.styles.layer = "float"

    def pin(self, pinned: PinnedHeader) -> None:
        """Draw the one header the window's top row needs, or none, in the column its message
        draws it in, so it sits and wraps exactly as the flow's own header does."""
        for header in pinned.headers:
            self.update_block(header)
        if pinned.headers:
            if self.styles.width is None or self.styles.width.value != pinned.width:
                self.styles.width = pinned.width
            if self.styles.offset.x.value != pinned.x:
                self.styles.offset = (pinned.x, 0)
        self.display = bool(pinned.headers)


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
        from toad.widgets.agent_activity import AgentActivityPresentation

        super().__init__(AgentActivityPresentation.group[0])
        self._category = category
        self.source = source

    @property
    def commit_claim(self):
        return block_claim(self.source)

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._category
