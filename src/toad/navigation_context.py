"""Navigation context and its owning capability, without UI imports."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from agent_comms.repo import Checkout
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.navigation_target import NavigationTarget


@dataclass(frozen=True)
class NavigationContext:
    app: ToadApp
    owner_mode: str
    project_path: Checkout
    actor: str


class NavigationOwner:
    """A view that navigates: it supplies context, targets supply behavior, App owns execution.

    Only a navigating view shows the channels sidebar, whose rows open their
    targets through the selected view.
    """

    shows_channels = True

    @property
    @abstractmethod
    def navigation_context(self) -> NavigationContext: ...

    def remember_direct_target(self, target: str) -> None:
        """Optional view-local return-to-DM intent."""

    async def open_sidebar_target(self, target: NavigationTarget) -> str:
        target.selected(self)
        return await target.open(self.navigation_context)
