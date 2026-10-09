from __future__ import annotations
from toad.block_navigation import ConversationBlock, ChildBlockCursor
from functools import cached_property

from agent_comms.mro_dispatch import handles
from toad.core.projection import MroProjection
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.message_divider import MessageClock, LiveMessageClock, MessageDivider
from toad.widgets.route_header import RouteHeader
from toad import response_delivery
from toad.widgets.message_filter import (
    CategorizedBlock,
    MessageCategory,
)

class AgentResponse(MroProjection, ConversationBlock, CategorizedBlock, VerticalGroup):
    """An agent's message: its headers, then its text drawn as prepared lines."""

    DEFAULT_CSS = """
    AgentResponse {
        height: auto;
        min-height: 1;
        padding: 0 0 0 0;
    }
    """

    DEFAULT_CLASSES = "block"

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._message_category

    def __init__(self, markdown: str | None = None, *, delivery: response_delivery.ResponseDelivery = response_delivery.UnroutedResponse(),
                 category: type[MessageCategory] | None = None,
                 show_divider: bool = True, clock: MessageClock = LiveMessageClock()) -> None:
        self._message_category = category or delivery.category
        presentation = self.dispatch_sync(delivery, clock, show_divider)
        super().__init__(classes=presentation.get("classes"))
        self._prefix = presentation["prefix"]
        self.body = LineMarkdown(markdown or "")
        self.delivery = delivery

    def compose(self) -> ComposeResult:
        yield from self._prefix
        yield self.body

    async def append_fragment(self, fragment: str) -> None:
        self.loading = False
        self.body.append(fragment)

    async def finish_stream(self) -> None:
        """Appends draw as they arrive; there is no stream to flush."""

    @handles(response_delivery.UnroutedResponse)
    def ordinary_prefix(self, delivery, clock, show_divider):
        return {"prefix": (MessageDivider("Agent", clock=clock),) if show_divider else ()}

    @handles(response_delivery.RoutedResponse)
    def routed_prefix(self, delivery, clock, show_divider):
        return {
            "prefix": (
                (MessageDivider("Outbound", clock=clock), RouteHeader(delivery.route))
                if show_divider else ()
            ),
            "classes": f"{self.DEFAULT_CLASSES} -routed",
        }

    @cached_property
    def block_cursor(self):
        return ChildBlockCursor(self)
