from __future__ import annotations

from textual.reactive import var
from textual.widget import Widget
from toad.widgets.streaming_markdown import StreamingMarkdown
from agent_comms.routing import MessageRoute
from toad.widgets.route_header import RouteHeader
from toad.widgets.message_divider import MessageDivider
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
    def prefix(self) -> tuple[Widget, ...]: ...

    def decorate(self, widget: Widget) -> None:
        pass


@dataclass(frozen=True)
class UnroutedResponse(ResponseDelivery):
    @property
    def category(self):
        return AgentCategory

    def prefix(self):
        return (MessageDivider("Agent"),)


@dataclass(frozen=True)
class RoutedResponse(ResponseDelivery):
    route: MessageRoute

    @property
    def category(self):
        return OutboundCategory

    def prefix(self):
        return MessageDivider("Outbound"), RouteHeader(self.route)

    def decorate(self, widget):
        widget.add_class("-routed")


class AgentResponse(CategorizedBlock, StreamingMarkdown):
    DEFAULT_CLASSES = "block"
    block_cursor_offset = var(-1)

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._message_category

    def __init__(
        self,
        markdown: str | None = None,
        *,
        delivery: ResponseDelivery = UnroutedResponse(),
        category: type[MessageCategory] | None = None,
        paginate: bool = True,
        show_divider: bool = True,
    ) -> None:
        self._message_category = category or delivery.category
        super().__init__(
            markdown,
            paginate=paginate,
            prefix=delivery.prefix() if show_divider else (),
        )
        self.delivery = delivery
        delivery.decorate(self)

    def block_cursor_clear(self) -> None:
        self.block_cursor_offset = -1

    def block_cursor_up(self) -> Widget | None:
        if self.block_cursor_offset == -1:
            if self.children:
                self.block_cursor_offset = len(self.children) - 1
            else:
                return None
        else:
            self.block_cursor_offset -= 1

        if self.block_cursor_offset == -1:
            return None
        try:
            return self.children[self.block_cursor_offset]
        except IndexError:
            self.block_cursor_offset = -1
            return None

    def block_cursor_down(self) -> Widget | None:
        if self.block_cursor_offset == -1:
            if self.children:
                self.block_cursor_offset = 0
            else:
                return None
        else:
            self.block_cursor_offset += 1
        if self.block_cursor_offset >= len(self.children):
            self.block_cursor_offset = -1
            return None
        try:
            return self.children[self.block_cursor_offset]
        except IndexError:
            self.block_cursor_offset = -1
            return None

    def get_cursor_block(self) -> Widget | None:
        if self.block_cursor_offset == -1:
            return None
        return self.children[self.block_cursor_offset]

    def block_select(self, widget: Widget) -> None:
        self.block_cursor_offset = self.children.index(widget)
