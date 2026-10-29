"""Live messages own their displayed dividers and mounted lifetime."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, ClassVar
from weakref import WeakSet

from textual.widget import Widget

from toad.line_blocks import Divider

if TYPE_CHECKING:
    from toad.widgets.message_divider import MessageDivider


class MessageRowOwner(Widget):
    """A complete live message, not a divider or another message-menu surface."""

    message_dividers: tuple[MessageDivider, ...]
    _mounted: ClassVar[WeakSet[MessageRowOwner]] = WeakSet()

    def _on_mount(self) -> None:
        self._mounted.add(self)

    def _on_unmount(self) -> None:
        self._mounted.discard(self)

    @classmethod
    def mounted_in(cls, window: Widget) -> Iterator[MessageRowOwner]:
        """Native ancestry owns membership, including moves without remounting."""
        return (message for message in cls._mounted if window in message.ancestors)

    def sticky_header(self, row: int) -> tuple[Divider, ...]:
        """Pin the displayed block only after its divider has left the viewport."""
        header_height = sum(divider.outer_size.height + divider.styles.margin.height
                            for divider in self.message_dividers)
        return tuple(divider.block for divider in self.message_dividers) if row >= header_height else ()
