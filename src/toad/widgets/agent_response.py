from __future__ import annotations
from toad.block_navigation import ConversationBlock, ChildBlockCursor
from functools import cached_property

from agent_comms.mro_dispatch import handles
from toad.core.projection import MroProjection
from toad.widgets.streaming_markdown import StreamingMarkdown
from toad.widgets.message_divider import MessageClock, LiveMessageClock, MessageDivider
from toad.widgets.route_header import RouteHeader
from toad import response_delivery
from toad.widgets.message_filter import (
    CategorizedBlock,
    MessageCategory,
)

class AgentResponse(MroProjection, ConversationBlock, CategorizedBlock, StreamingMarkdown):
    DEFAULT_CSS = """
    AgentResponse {
        min-height: 1;
        padding: 0 0 0 0;
        overflow-x: auto;
        scrollbar-size-horizontal: 0;
        layout: stream;
    }
    """

    DEFAULT_CLASSES = "block"

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._message_category

    def __init__(self, markdown: str | None = None, *, delivery: response_delivery.ResponseDelivery = response_delivery.UnroutedResponse(),
                 category: type[MessageCategory] | None = None,
                 paginate: bool = True, show_divider: bool = True, clock: MessageClock = LiveMessageClock()) -> None:
        self._message_category = category or delivery.category
        super().__init__(
            markdown,
            paginate=paginate,
            **self.dispatch_sync(delivery, clock, show_divider),
        )
        self.delivery = delivery

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
