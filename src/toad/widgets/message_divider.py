"""A full-width, timestamped separator owned by one displayed message."""

from __future__ import annotations
from toad.block_navigation import ConversationBlock
from toad.block_content import BlockContent

import math
import time

from textual.content import Content
from textual.geometry import Size
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.widgets import Static

from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation


class MessageDivider(BlockContent, Static):
    """Keep timestamps with the message block, not a second transcript row."""

    DEFAULT_CSS = """
    MessageDivider {
        width: 1fr;
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
        text-wrap: nowrap;
    }
    MessageDivider:ansi { color: ansi_bright_black; }
    """

    def __init__(self, label: str, *, timestamp: float | None = None) -> None:
        super().__init__(markup=False)
        self.label = label
        observed = time.time() if timestamp is None else timestamp
        if type(observed) in (int, float) and math.isfinite(observed):
            try:
                self.clock = time.strftime("%H:%M:%S", time.localtime(observed))
                self.tooltip = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(observed))
            except (OverflowError, OSError, ValueError):
                self.clock = "time unknown"
        else:
            self.clock = "time unknown"

    def render(self) -> Content:
        title = f" {self.label} · {self.clock} "
        width = max(0, self.size.width)
        if width <= len(title):
            return Content(title).truncate(width, ellipsis=True)
        left = (width - len(title)) // 2
        right = max(0, width - left - len(title))
        return Content.assemble(
            ("─" * left, "$text-muted"),
            (title, "bold $text-muted"),
            ("─" * right, "$text-muted"),
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

    def __init__(self, category: type[MessageCategory]) -> None:
        super().__init__("Agent")
        self._category = category

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._category
