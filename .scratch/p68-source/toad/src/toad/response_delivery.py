"""Original response routing and semantic category, without native resources."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.routing import MessageRoute

if TYPE_CHECKING:
    from toad.widgets.message_filter import MessageCategory


class ResponseDelivery(DeclaredFamily, affix="Response"):
    @classmethod
    def from_route(cls, route: MessageRoute | None) -> ResponseDelivery:
        """Decode the optional routing annotation at the ACP/transcript boundary."""
        return UnroutedResponse() if route is None else RoutedResponse(route)

    @property
    @abstractmethod
    def category(self) -> type[MessageCategory]: ...


@dataclass(frozen=True)
class UnroutedResponse(ResponseDelivery):
    @property
    def category(self):
        from toad.widgets.message_filter import AgentCategory
        return AgentCategory


@dataclass(frozen=True)
class RoutedResponse(ResponseDelivery):
    route: MessageRoute

    @property
    def category(self):
        from toad.widgets.message_filter import OutboundCategory
        return OutboundCategory
