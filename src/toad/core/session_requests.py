"""Existing workspace intents carry their behavior through the Command contract."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

from agent_comms.command import Command
from toad.core.events import CoreEvent


class WorkspaceSessionRequest(Command, CoreEvent):
    """The original session admission owner applies each declared request."""

    @abstractmethod
    async def apply(self, admission) -> None: ...


@dataclass(frozen=True)
class SessionNavigate(WorkspaceSessionRequest):
    mode_name: str
    direction: Literal[-1, +1]

    async def apply(self, admission) -> None:
        modes = [tab.mode_name for tab in admission.tabs]
        if admission.app.selected_mode in modes:
            await admission.app.select_session(
                modes[(modes.index(admission.app.selected_mode) + self.direction) % len(modes)]
            )


@dataclass(frozen=True)
class SessionSwitch(WorkspaceSessionRequest):
    mode_name: str

    async def apply(self, admission) -> None:
        await admission.app.select_session(self.mode_name)


@dataclass(frozen=True)
class SessionNew(WorkspaceSessionRequest):
    path: str
    agent: str
    prompt: str

    async def apply(self, admission) -> None:
        admission.app.run_worker(partial(admission.launch, self.agent,
            project_path=Path(self.path), initial_prompt=self.prompt))


@dataclass(frozen=True)
class SessionCreate(WorkspaceSessionRequest):
    source_mode: str

    async def apply(self, admission) -> None:
        await admission.create_from(self.source_mode)


@dataclass(frozen=True)
class SessionRename(WorkspaceSessionRequest):
    mode_name: str
    name: str

    async def apply(self, admission) -> None:
        name = self.name.strip()
        source = admission.source(self.mode_name)
        if name and source is not None:
            await source.conversation.rename_session(name)


@dataclass(frozen=True)
class SessionArchive(WorkspaceSessionRequest):
    mode_name: str

    async def apply(self, admission) -> None:
        await admission.close(self.mode_name)


@dataclass(frozen=True)
class SessionClose(WorkspaceSessionRequest):
    name: str

    async def apply(self, admission) -> None:
        await admission.close(self.name)


@dataclass(frozen=True)
class LaunchAgent(WorkspaceSessionRequest):
    identity: str
    session_id: str | None = None
    pk: int | None = None
    prompt: str | None = None

    async def apply(self, admission) -> None:
        admission.app.run_worker(partial(admission.launch, self.identity,
            agent_session_id=self.session_id, session_pk=self.pk, initial_prompt=self.prompt))
