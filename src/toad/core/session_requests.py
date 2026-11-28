"""Existing workspace intents carry their behavior through the Command contract."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Literal

from agent_comms.planning.command import Command
from formbridge.operations import OperationKind
from agent_comms.projects.checkouts import Checkout

from toad.constants import WELCOME
from toad.core.link_context_changed import CoreEvent
from toad.navigation_context import NavigationContext
from toad.navigation_target import NavigationTarget

if TYPE_CHECKING:
    from toad.session_navigation import SessionNavigation


class SessionRequestApply(OperationKind):
    """A workspace session request applied by the session navigator; requests run side by
    side, in the order they were published."""


class WorkspaceSessionRequest(Command, CoreEvent):
    """The workspace session manager applies each declared request."""

    @abstractmethod
    async def apply(self, navigation: SessionNavigation) -> None: ...


@dataclass(frozen=True)
class SessionNavigate(WorkspaceSessionRequest):
    """Cycle from the selected tab: the request needs only its direction."""

    direction: Literal[-1, +1]

    async def apply(self, navigation: SessionNavigation) -> None:
        modes = [tab.mode_name for tab in navigation.tabs]
        if navigation.app.selected_mode in modes:
            await navigation.app.select_session(
                modes[(modes.index(navigation.app.selected_mode) + self.direction) % len(modes)]
            )


@dataclass(frozen=True)
class SessionSwitch(WorkspaceSessionRequest):
    mode_name: str

    async def apply(self, navigation: SessionNavigation) -> None:
        await navigation.app.select_session(self.mode_name)


@dataclass(frozen=True)
class SessionNew(WorkspaceSessionRequest):
    path: str
    agent: str
    prompt: str

    async def apply(self, navigation: SessionNavigation) -> None:
        navigation.app.run_worker(partial(navigation.launch, self.agent,
            project=Checkout.checked(self.path), initial_prompt=self.prompt))


@dataclass(frozen=True)
class SessionRename(WorkspaceSessionRequest):
    mode_name: str
    name: str

    async def apply(self, navigation: SessionNavigation) -> None:
        name = self.name.strip()
        source = navigation.source(self.mode_name)
        if name and source is not None:
            await source.conversation.rename_session(name)


@dataclass(frozen=True)
class SessionMove(WorkspaceSessionRequest):
    """Move a tab ``steps`` places in the shared tab order (negative: toward the start)."""

    mode_name: str
    steps: int

    async def apply(self, navigation: SessionNavigation) -> None:
        if entry := navigation.get(self.mode_name):
            await navigation.app.tab_order.move(entry.identity, self.steps)
            navigation.publish()


@dataclass(frozen=True)
class TargetOpen(WorkspaceSessionRequest):
    """Open a thread or channel as its sidebar row does, from home: a row's tap or a link
    naming it. Home is the origin whichever tab the request came from."""

    target: NavigationTarget

    async def apply(self, navigation: SessionNavigation) -> None:

        app = navigation.app
        await self.target.open(NavigationContext(app=app, owner_mode=WELCOME,
                                                 project_path=app.project_dir, actor=""))


@dataclass(frozen=True)
class SessionClose(WorkspaceSessionRequest):
    mode_name: str

    async def apply(self, navigation: SessionNavigation) -> None:
        await navigation.close(self.mode_name)
