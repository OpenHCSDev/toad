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

from agent_comms.comms import wire
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from agent_comms.transcripts import TranscriptReadIdentity
from agent_comms.ui_model.observation import (
    AwaitedRead, ReadNotifications, ReadTranscript, RefreshTranscript,
)


class CoordinationTranscriptReader(ABC):
    """One agent's observed reads, and the read-side Comms service its other work binds."""

    def __init__(self):
        self._reader = None
        self._lock = asyncio.Lock()

    @abstractmethod
    async def read(self, request: AwaitedRead): ...

    async def service(self, root):
        return await asyncio.to_thread(wire, root)

    def observed(self, access) -> CoordinationTranscriptReader:
        return ObservedTranscriptReader(access)

    @asynccontextmanager
    async def bind(self, root: str):
        async with self._lock:
            if self._reader is None or self._reader.root != Path(root).expanduser():
                self._reader = await self.service(root)
            reader = self._reader
        # The lock owns service initialization/replacement, not projections.
        # Each caller retains this exact root service; its canonical stores own
        # read transactions and the Agent fences publication after awaits.
        yield reader

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


class DetachedTranscriptReader(CoordinationTranscriptReader):
    """An operational Agent no view has attached: nothing presents a transcript."""

    async def read(self, request):
        raise RuntimeError("Observed reads serve a view; no view is attached to this agent")


class ObservedTranscriptReader(CoordinationTranscriptReader):
    """Reads answered by the application's observation service."""

    def __init__(self, access):
        super().__init__()
        self.access = access

    async def read(self, request):
        return await self.access.read(request)

    async def service(self, root):
        shared = self.access.observed_service
        if shared is not None and shared.root == Path(root).expanduser():
            return shared
        return await super().service(root)

    def observed(self, access):
        return self if self.access is access else super().observed(access)
