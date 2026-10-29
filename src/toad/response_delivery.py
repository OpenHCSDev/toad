"""Original response routing and semantic category, without native resources."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.routing import MessageRoute, NoMessageRoute

if TYPE_CHECKING:
    from agent_comms.ui_model.message_category import MessageCategory


class ResponseDelivery(DeclaredFamily, affix="Response"):
    @classmethod
    def from_route(cls, route: MessageRoute | NoMessageRoute) -> ResponseDelivery:
        """Derive response delivery from the route's declared presence."""
        return next(map(RoutedResponse, route.present()), UnroutedResponse())

    @property
    @abstractmethod
    def category(self) -> type[MessageCategory]: ...


@dataclass(frozen=True)
class UnroutedResponse(ResponseDelivery):
    @property
    def category(self):
        from agent_comms.ui_model.message_category import AgentCategory
        return AgentCategory


@dataclass(frozen=True)
class RoutedResponse(ResponseDelivery):
    route: MessageRoute

    @property
    def category(self):
        from agent_comms.ui_model.message_category import OutboundCategory
        return OutboundCategory
