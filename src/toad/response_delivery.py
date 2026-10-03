"""The original response delivery owns routing and its rendering hooks."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.routing import MessageRoute

if TYPE_CHECKING:
    from textual.widget import Widget
    from toad.widgets.message_divider import MessageClock
    from toad.widgets.message_filter import MessageCategory


class ResponseDelivery(DeclaredFamily, affix="Response"):
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
        from toad.widgets.message_filter import AgentCategory
        return AgentCategory

    def prefix(self, clock: MessageClock):
        from toad.widgets.message_divider import MessageDivider
        return (MessageDivider("Agent", clock=clock),)


@dataclass(frozen=True)
class RoutedResponse(ResponseDelivery):
    route: MessageRoute

    @property
    def category(self):
        from toad.widgets.message_filter import OutboundCategory
        return OutboundCategory

    def prefix(self, clock: MessageClock):
        from toad.widgets.message_divider import MessageDivider
        from toad.widgets.route_header import RouteHeader
        return MessageDivider("Outbound", clock=clock), RouteHeader(self.route)

    def decorate(self, widget):
        widget.add_class("-routed")


