"""Navigation context and its owning capability, without UI imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.navigation_target import NavigationTarget


@dataclass(frozen=True)
class NavigationContext:
    app: ToadApp
    owner_mode: str
    project_path: Path
    actor: str


class NavigationOwner:
    """Views supply context, targets supply behavior, App owns execution."""

    @property
    def navigation_context(self) -> NavigationContext:
        raise NotImplementedError

    def remember_direct_target(self, target: str) -> None:
        """Optional view-local return-to-DM intent."""

    async def open_sidebar_target(self, target: NavigationTarget) -> str:
        target.selected(self)
        return await target.open(self.navigation_context)
