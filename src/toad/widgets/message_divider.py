"""A full-width, timestamped separator owned by one displayed message."""

from __future__ import annotations
from toad.block_navigation import ConversationBlock
from toad.block_content import BlockContent

import time
from dataclasses import dataclass, replace
from typing import ClassVar

from rich.style import Style
from textual.geometry import Size
from textual.selection import Selection
from textual.strip import Strip
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.widget import Widget

from ui_theme.effects import NEW_MESSAGE

from toad.line_blocks import AgentRole, Divider
from toad.textual_colours import Animated
from toad.widgets.transcript_lines import LineTheme, LinkedRows, PreparedLines, RichLineRenderer, link_place

from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation


class MessageClock:
    """When a displayed message happened."""

    # True for a message happening now (not one read back from history).
    fresh: ClassVar[bool] = False

    # Each clock says when: now, a recorded time, or not known.
    timestamp: float | None

    def display(self) -> tuple[str, str | None]:
        """The time as a rule shows it, and in full with its zone."""
        timestamp = self.timestamp
        if timestamp is None:
            return "time unknown", None
        try:
            local = time.localtime(timestamp)
            return time.strftime("%Y-%m-%d %H:%M:%S", local), time.strftime("%Y-%m-%d %H:%M:%S %Z", local)
        except (OverflowError, OSError, ValueError):
            return "time unknown", None

    @classmethod
    def recorded(cls, timestamp: float | None) -> MessageClock:
        return UnknownMessageClock() if timestamp is None else RecordedMessageClock(timestamp)


class LiveMessageClock(MessageClock):
    fresh = True

    @property
    def timestamp(self) -> float:
        return time.time()


@dataclass(frozen=True)
class RecordedMessageClock(MessageClock):
    timestamp: float


class UnknownMessageClock(MessageClock):
    timestamp = None


class MessageDivider(LinkedRows, Animated, BlockContent, Widget):
    """The rule above a live message: the same `Divider` block saved history draws, drawn the same way.

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
        super().__init__()
        self.block = replace(block, timestamp=clock.timestamp)
        self.fresh = clock.fresh
        self.tooltip = clock.display()[1]
        self._link_place = link_place()
        self._lines: tuple[LineTheme, PreparedLines] | None = None

    def on_mount(self) -> None:
        if self.fresh:
            # Once: a divider moved to another parent is not a new message.
            self.fresh = False
            self.run_effect(NEW_MESSAGE.ending_at(self.block.role.colour))

    def on_unmount(self) -> None:
        self.stop_effect()

    def _drawn(self, theme: LineTheme, width: int) -> PreparedLines:
        return PreparedLines(width, RichLineRenderer(theme, width).rows((self.block,)))

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if y or not width:
            return self.blank_row(width)
        theme = self.app.colours.line_theme
        animation = self.animation
        if animation is not None:
            mix = animation.frame()
            colour = self.app.colours.mixed(mix.start, mix.end, mix.amount)
            lines = self._drawn(theme.with_colour(self.block.role.colour, Style(color=colour.rich_color)), width)
        else:
            if self._lines is None or self._lines[0] is not theme or self._lines[1].width != width:
                self._lines = theme, self._drawn(theme, width)
            lines = self._lines[1]
        return self.on_background(lines.strips_at(self._link_place)[0])

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        return selection.extract(self.block.label), "\n"

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return 1


class AgentActivityDivider(ConversationBlock, SnapshotPresentation, CategorizedBlock, MessageDivider):
    """A decorative role boundary filtered with the activity that follows it."""

    ALLOW_SELECT = False

    def __init__(self, category: type[MessageCategory], *, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__(Divider.titled("Agent", AgentRole), clock=clock)
        self._category = category

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._category
