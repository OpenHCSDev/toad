"""A view's reads, answered by Core's observation service.

The UI process does not read Core's transcript stores or ask the live owner
for its goal snapshot and input delivery. A page read, a published page's
currency check, message notifications and those owner reads are requests to
the observation process (``agent_comms.ui_model.observation``) that
``CoordinationAccess`` owns; the answer arrives decoded (a finished page and
its witness, an owner snapshot), or as the exception the read raised. The
in-process service binding remains for the work that has not moved: the owner
presentation that settles turns, owner actions and input capture.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path

from agent_comms.active_route import resolve_comms_route
from agent_comms.comms import Comms
from agent_comms.launch_runtime import LaunchRuntime
from agent_comms.acp_extension import TranscriptDraftUpdate, TranscriptSnapshotUpdate
from agent_comms.transcripts import TranscriptReadIdentity
from agent_comms.ui_model.observation import (
    AwaitedRead, ReadNotifications, ReadTranscript, ReadTranscriptUpdate, RefreshTranscript,
)


class CoordinationTranscriptReader(ABC):
    """One agent's observed reads, and the read-side Comms service its other work binds."""

    @abstractmethod
    async def read(self, request: AwaitedRead): ...

    @abstractmethod
    async def service(self, root) -> Comms: ...

    async def thread_presentation(self, root: str, thread: str):
        """Read one thread presentation through this reader's bound service."""
        from toad.owner_preparation import read_thread_presentation

        async with self.bind(root) as reader:
            return await asyncio.to_thread(read_thread_presentation, reader, thread)

    @asynccontextmanager
    async def bind(self, root: str):
        yield await self.service(root)

    async def publication(self, update: TranscriptSnapshotUpdate) -> TranscriptSnapshotUpdate:
        """The published page while its witness is current, else the current page."""
        identity = update.identity
        current = await self.read(RefreshTranscript(identity.root, identity))
        return update if current is None else current

    async def notifications(self, root, references):
        return await self.read(ReadNotifications(root, tuple(references)))

    async def page(self, root, thread, *, before=None, after=None, through=None,
                   read_identity: TranscriptReadIdentity | None = None,
                   historical_source: str | None = None):
        snapshot = await self.snapshot(root, thread, before=before, after=after, through=through,
                                       read_identity=read_identity, historical_source=historical_source)
        return snapshot.page

    async def snapshot(self, root, thread, *, before=None, after=None, through=None,
                       read_identity: TranscriptReadIdentity | None = None,
                       historical_source: str | None = None) -> TranscriptSnapshotUpdate:
        return await self.read(ReadTranscript(
            root, thread, before=before, after=after, through=through,
            read_identity=read_identity, historical_source=historical_source))

    async def updates(
        self, root: str, thread: str, previous: TranscriptReadIdentity | None,
        *, read_identity: TranscriptReadIdentity | None = None,
    ) -> TranscriptSnapshotUpdate | TranscriptDraftUpdate:
        return await self.read(ReadTranscriptUpdate(
            root, thread, previous=previous, read_identity=read_identity))


class DetachedTranscriptReader(CoordinationTranscriptReader):
    """An operational Agent no view has attached: nothing presents a transcript."""

    def __init__(self, runtime: LaunchRuntime):
        self.runtime = runtime
        self._reader: Comms | None = None
        self._lock = asyncio.Lock()

    async def service(self, root):
        async with self._lock:
            if self._reader is None or self._reader.root != Path(root).expanduser():
                self._reader = await asyncio.to_thread(
                    Comms, resolve_comms_route(root), runtime=self.runtime,
                )
            return self._reader

    async def read(self, request):
        raise RuntimeError("Observed reads serve a view; no view is attached to this agent")


class ObservedTranscriptReader(CoordinationTranscriptReader):
    """Reads answered by the application's observation service."""

    def __init__(self, access):
        self.access = access

    async def read(self, request):
        return await self.access.read(request)

    async def service(self, root):
        return await self.access.preparation.run_thread(
            lambda: self.access.acquire(resolve_comms_route(root)),
        )
