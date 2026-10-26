"""Existing workspace intents carry their behavior through the Command contract."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Literal

from agent_comms.command import Command
from agent_comms.repo import Checkout
from toad.core.events import CoreEvent

if TYPE_CHECKING:
    from toad.session_navigation import SessionNavigation


class WorkspaceSessionRequest(Command, CoreEvent):
    """The workspace session manager applies each declared request."""

    @abstractmethod
    async def apply(self, navigation: SessionNavigation) -> None: ...


@dataclass(frozen=True)
class SessionNavigate(WorkspaceSessionRequest):
    mode_name: str
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
class SessionArchive(WorkspaceSessionRequest):
    mode_name: str

    async def apply(self, navigation: SessionNavigation) -> None:
        await navigation.close(self.mode_name)



@dataclass(frozen=True)
class LaunchAgent(WorkspaceSessionRequest):
    identity: str
    session_id: str | None = None
    pk: int | None = None
    prompt: str | None = None

    async def apply(self, navigation: SessionNavigation) -> None:
        navigation.app.run_worker(partial(navigation.launch, self.identity,
            project=navigation.app.project_dir, agent_session_id=self.session_id, session_pk=self.pk, initial_prompt=self.prompt))
