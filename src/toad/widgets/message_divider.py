"""A full-width, timestamped separator owned by one displayed message."""

from __future__ import annotations
from toad.block_navigation import CategorizedBlock, ConversationBlock
from toad.block_content import BlockContent

from dataclasses import replace

from rich.style import Style
from textual.geometry import Size
from textual.selection import Selection
from textual._paint_state import PaintState
from textual.strip import Strip
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.widget import Widget

from ui_theme.effects import NEW_MESSAGE, Mix

from toad.line_blocks import Divider, LineBlock
from toad.frame_presentation import Animated
from toad.message_rows import MessageClock, LiveMessageClock, MessageRow
from toad.widgets.linked_rows import LinkedRows, MessageRowBlock
from toad.widgets.transcript_lines import LineTheme, PreparedLines, RichLineRenderer, link_place

from agent_comms.ui_model.message_category import MessageCategory
from toad.widgets.committed_presentation import CommitParticipant


class SingleLineBlock(LinkedRows, BlockContent, Widget):
    """One semantic line block, drawn exactly as transcript history draws it."""

    DEFAULT_CSS = "SingleLineBlock { width: 1fr; height: 1; }"

    def __init__(self, block: LineBlock) -> None:
        super().__init__()
        self.block = block
        self._link_place = link_place()
        self._lines: tuple[LineTheme, PreparedLines] | None = None

    @property
    def line_theme(self) -> LineTheme:
        return self.app.colours.line_theme

    def update_block(self, block: LineBlock) -> None:
        if block != self.block:
            self.block, self._lines = block, None
            self.refresh()

    def _drawn(self, theme: LineTheme, width: int) -> PreparedLines:
        return PreparedLines(width, RichLineRenderer(theme, width).rows((self.block,)))

    def render_line(self, y: int, paint: PaintState) -> Strip:
        width = self.size.width
        if y or not width:
            return self.blank_row(width, paint)
        theme = self.line_theme
        if self._lines is None or self._lines[0] != theme or self._lines[1].width != width:
            self._lines = theme, self._drawn(theme, width)
        return self.on_background(self._lines[1].strips_at(self._link_place)[0], paint, y)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        return selection.extract(self.block.selection_text), "\n"

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return 1


class MessageDivider(Animated[Mix], SingleLineBlock):
    """The rule above a live message: the same `Divider` block saved history draws.

    A message that has just arrived fades in from the accent colour.
    """

    DEFAULT_CSS = """
    MessageDivider {
        width: 1fr;
        height: 1;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, block: Divider, *, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__(replace(block, timestamp=clock.timestamp))
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


class AgentActivityDivider(ConversationBlock, CommitParticipant, CategorizedBlock, SingleLineBlock):
    """The shared activity-group row, filtered with the activity that follows it."""

    ALLOW_SELECT = False

    def __init__(self, category: type[MessageCategory], source: CommitParticipant) -> None:
        from toad.widgets.agent_activity import AgentActivityPresentation

        super().__init__(AgentActivityPresentation.group[0])
        self._category = category
        self.source = source

    @property
    def commit_claim(self):
        return self.source.commit_claim

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._category
