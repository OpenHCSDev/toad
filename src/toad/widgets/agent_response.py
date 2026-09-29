from __future__ import annotations
from toad.block_navigation import ConversationBlock, ChildBlockCursor
from functools import cached_property

from textual.widget import Widget
from toad.widgets.streaming_markdown import StreamingMarkdown
from agent_comms.routing import MessageRoute
from toad.widgets.route_header import RouteHeader
from toad.widgets.message_divider import MessageDivider, MessageClock, LiveMessageClock
from toad.widgets.message_filter import (
    CategorizedBlock,
    MessageCategory,
    OutboundCategory,
    AgentCategory,
)

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ResponseDelivery(ABC):
    @classmethod
    def from_route(cls, route: MessageRoute | None) -> ResponseDelivery:
        """Decode the optional routing annotation at the ACP/transcript boundary."""
        return UnroutedResponse() if route is None else RoutedResponse(route)

    @property
    @abstractmethod
    def category(self) -> type[MessageCategory]: ...

    @abstractmethod
    def prefix(self, clock: MessageClock) -> tuple[Widget, ...]: ...

    def decorate(self, widget: Widget) -> None:
        pass


@dataclass(frozen=True)
class UnroutedResponse(ResponseDelivery):
    @property
    def category(self):
        return AgentCategory

    def prefix(self, clock: MessageClock):
        return (MessageDivider("Agent", clock=clock),)


@dataclass(frozen=True)
class RoutedResponse(ResponseDelivery):
    route: MessageRoute

    @property
    def category(self):
        return OutboundCategory

    def prefix(self, clock: MessageClock):
        return MessageDivider("Outbound", clock=clock), RouteHeader(self.route)

    def decorate(self, widget):
        widget.add_class("-routed")


class AgentResponse(ConversationBlock, CategorizedBlock, StreamingMarkdown):
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

    def __init__(self, markdown: str | None = None, *, delivery: ResponseDelivery = UnroutedResponse(),
                 category: type[MessageCategory] | None = None,
                 paginate: bool = True, show_divider: bool = True, clock: MessageClock = LiveMessageClock()) -> None:
        self._message_category = category or delivery.category
        super().__init__(
            markdown,
            paginate=paginate,
            prefix=delivery.prefix(clock) if show_divider else (),
        )
        self.delivery = delivery
        delivery.decorate(self)

    @cached_property
    def block_cursor(self):
        return ChildBlockCursor(self)
