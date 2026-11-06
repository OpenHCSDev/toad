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


class NavigationScope:
    """An ancestor its descendants open targets through."""

    @property
    @abstractmethod
    def navigation_owner(self) -> NavigationOwner: ...


class NavigationOwner:
    """A view that navigates: it supplies context, targets supply behavior, App owns execution.

    Only a navigating view shows the shared channels sidebar, and that sidebar's rows
    open through it.
    """

    shows_channels = True

    @property
    def navigation_owner(self) -> NavigationOwner:
        return self

    @property
    @abstractmethod
    def navigation_context(self) -> NavigationContext: ...

    def remember_direct_target(self, target: str) -> None:
        """Optional view-local return-to-DM intent."""

    async def open_sidebar_target(self, target: NavigationTarget) -> None:
        target.selected(self)
        await target.open(self.navigation_context)

    @property
    def navigation_app(self) -> ToadApp:
        """The app this owner's notices go to."""
        return self.navigation_context.app

    async def open_direct_messages(self) -> None:
        """Open this view's direct-message destination when it has one."""
        self.navigation_app.notify(
            "Direct messages are unavailable from this view", title="Direct messages"
        )


class NavigationUnavailable(RuntimeError):
    """Navigation was asked for while no navigating view is selected."""


class NoNavigationOwner(NavigationOwner):
    """The owner the workspace answers while no navigating view is selected: a file preview, or
    no view at all. It refuses instead of reaching a closed view.
    """

    shows_channels = False

    def __init__(self, app: ToadApp) -> None:
        self.app = app

    @property
    def navigation_app(self) -> ToadApp:
        return self.app

    @property
    def navigation_context(self) -> NavigationContext:
        raise NavigationUnavailable("No navigating view is selected")

    async def open_sidebar_target(self, target: NavigationTarget) -> None:
        """A target asked of no navigating view is refused with a notice, not a traceback."""
        self.app.notify("Nothing opens from this view", title="Navigation")
