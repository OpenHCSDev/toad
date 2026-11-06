"""Navigation context and its owning capability, without UI imports."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from agent_comms.repo import Checkout
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.navigation_target import NavigationTarget
    from toad.workspace_chrome import WorkspaceChrome


@dataclass(frozen=True)
class NavigationContext:
    app: ToadApp
    owner_mode: str
    project_path: Checkout
    actor: str


class NavigationOwner:
    """A view that navigates: it supplies context, targets supply behavior, App owns execution.

    Only a navigating view shows the shared channels sidebar, and the chrome opens
    that sidebar's rows through it.
    """

    def present_channels(self, chrome: WorkspaceChrome) -> None:
        chrome.show_channels(self)

    @property
    @abstractmethod
    def navigation_context(self) -> NavigationContext: ...

    def remember_direct_target(self, target: str) -> None:
        """Optional view-local return-to-DM intent."""

    async def open_sidebar_target(self, target: NavigationTarget) -> str:
        target.selected(self)
        return await target.open(self.navigation_context)
