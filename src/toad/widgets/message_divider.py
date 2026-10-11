"""A full-width, timestamped separator owned by one displayed message."""

from __future__ import annotations
from toad.block_navigation import ConversationBlock
from toad.block_content import BlockContent

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from textual.content import Content
from textual.geometry import Size
from textual.style import Style
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.widgets import Static

from ui_theme.effects import NEW_MESSAGE

from toad.line_blocks import AgentRole, LineRole
from toad.textual_colours import Animated

from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation


class MessageClock(ABC):
    # True for a message happening now (not one read back from history).
    fresh: ClassVar[bool] = False

    @abstractmethod
    def display(self) -> tuple[str, str | None]: ...

    @classmethod
    def recorded(cls, timestamp: float | None) -> MessageClock:
        return UnknownMessageClock() if timestamp is None else RecordedMessageClock(timestamp)

    @staticmethod
    def format(timestamp: float) -> tuple[str, str | None]:
        try:
            local = time.localtime(timestamp)
            return time.strftime("%Y-%m-%d %H:%M:%S", local), time.strftime("%Y-%m-%d %H:%M:%S %Z", local)
        except (OverflowError, OSError, ValueError):
            return "time unknown", None


class LiveMessageClock(MessageClock):
    fresh = True

    def display(self) -> tuple[str, str | None]:
        return self.format(time.time())


@dataclass(frozen=True)
class RecordedMessageClock(MessageClock):
    timestamp: float

    def display(self) -> tuple[str, str | None]:
        return self.format(self.timestamp)


class UnknownMessageClock(MessageClock):
    def display(self) -> tuple[str, str | None]:
        return "time unknown", None


class MessageDivider(Animated, BlockContent, Static):
    """Keep timestamps with the message block, not a second transcript row.

    Drawn in its role's colour, as committed history draws the same divider.
    A message that has just arrived fades in from the accent colour.
    """

    DEFAULT_CSS = """
    MessageDivider {
        width: 1fr;
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
        text-wrap: nowrap;
    }
    """

    def __init__(self, label: str, role: type[LineRole], *,
                 clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__(markup=False)
        self.label = label
        self.role = role
        self.fresh = clock.fresh
        self.clock, self.tooltip = clock.display()

    def on_mount(self) -> None:
        if self.fresh:
            # Once: a divider moved to another parent is not a new message.
            self.fresh = False
            self.run_effect(NEW_MESSAGE.ending_at(self.role.colour))

    def on_unmount(self) -> None:
        self.stop_effect()

    def render(self) -> Content:
        title = f" {self.label} · {self.clock} "
        width = max(0, self.size.width)
        if width <= len(title):
            return Content(title).truncate(width, ellipsis=True)
        left = (width - len(title)) // 2
        right = max(0, width - left - len(title))
        colours = self.app.colours
        animation = self.animation
        if animation is None:
            colour = colours.colour(self.role.colour)
        else:
            mix = animation.frame()
            colour = colours.mixed(mix.start, mix.end, mix.amount)
        rule = Style(foreground=colour)
        return Content.assemble(
            ("─" * left, rule),
            (title, rule + Style(bold=True)),
            ("─" * right, rule),
        )

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        # The separator truncates to one line. Measuring render() before the
        # new native width is committed would wrap the *previous* width's rule
        # and incorrectly report two rows to a stream layout.
        return 1


class AgentActivityDivider(ConversationBlock, SnapshotPresentation, CategorizedBlock, MessageDivider):
    """A decorative role boundary filtered with the activity that follows it."""

    ALLOW_SELECT = False

    def __init__(self, category: type[MessageCategory], *, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__("Agent", AgentRole, clock=clock)
        self._category = category

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._category
