"""A live message's header is its displayed divider, independent of publication."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget

from toad.line_blocks import Divider

if TYPE_CHECKING:
    from toad.widgets.message_divider import MessageDivider


class MessageRowOwner(Widget):
    """A complete live message, not a divider or another message-menu surface."""

    message_dividers: tuple[MessageDivider, ...]

    def sticky_header(self, row: int) -> tuple[Divider, ...]:
        """Pin the displayed block once its divider's first row is above the window's top row,
        which is `row` of this message."""
        if not self.message_dividers:
            return ()
        first = self.message_dividers[0].styles.margin.top
        return tuple(divider.block for divider in self.message_dividers) if row > first else ()
