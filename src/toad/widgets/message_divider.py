"""A full-width, timestamped separator owned by one displayed message."""

from __future__ import annotations

import math
import time

from textual.content import Content
from textual.widgets import Static


class MessageDivider(Static):
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
