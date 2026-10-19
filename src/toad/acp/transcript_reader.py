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
from contextlib import asynccontextmanager

from agent_comms.route_selection import RouteSelection
from agent_comms.acp_extension import TranscriptDraftUpdate, TranscriptSnapshotUpdate
from agent_comms.ui_model.observation import (
    AwaitedRead, ReadTranscript, ReadTranscriptUpdate, RefreshTranscript,
    TranscriptPublicationState,
)


class CoordinationTranscriptReader:
    """The application's route-owned reads, shared by agents from construction."""

    def __init__(self, access):
        self.access = access

    async def read(self, request: AwaitedRead):
        observed = await self.access.preparation.run_thread(self.access.observation.observed)
        return await observed.process.read(request)

    async def service(self, root):
        return await self.access.preparation.run_thread(
            lambda: self.access.require(RouteSelection.capture(root)).service)

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

    async def page(self, root, thread, *, before=None, after=None, through=None,
                   historical_source: str | None = None):
        snapshot = await self.snapshot(root, thread, before=before, after=after, through=through,
                                       historical_source=historical_source)
        return snapshot.page

    async def snapshot(self, root, thread, *, before=None, after=None, through=None,
                       historical_source: str | None = None) -> TranscriptSnapshotUpdate:
        return await self.read(ReadTranscript(
            root, thread, before=before, after=after, through=through,
            historical_source=historical_source))

    async def updates(
        self, root: str, thread: str, previous: TranscriptPublicationState, *, after=None,
    ) -> TranscriptSnapshotUpdate | TranscriptDraftUpdate:
        return await self.read(ReadTranscriptUpdate(root, thread, after=after, previous=previous))
