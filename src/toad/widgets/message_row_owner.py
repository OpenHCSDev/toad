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
        """Pin the displayed block only after its divider has left the viewport."""
        header_height = sum(divider.outer_size.height + divider.styles.margin.height
                            for divider in self.message_dividers)
        return tuple(divider.block for divider in self.message_dividers) if row >= header_height else ()
