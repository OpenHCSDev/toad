"""Operational read custody; rich pager retirement does not discard source reuse."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from agent_comms.comms import wire
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from agent_comms.coordination_errors import StaleRevision
from agent_comms.transcripts import TranscriptRead, TranscriptPage, TranscriptReadIdentity

from toad.work_preparation import (
    ScopedWork, SerializedWork, ThreadWork, PreparationRuntime, WorkKey,
)


@dataclass(frozen=True)
class NativeTranscriptReadWork(ScopedWork[TranscriptPage],
                               SerializedWork[TranscriptPage], ThreadWork[TranscriptPage]):
    read: TranscriptRead

    @property
    def work_key(self) -> WorkKey:
        # The source owner names page content independently of annotations.
        # Notification/reader changes refresh their projections without causing
        # another native history read or inventing a second source identity.
        return WorkKey(NativeTranscriptReadWork, self.read.identity.content_identity)

    def prepare(self) -> TranscriptPage:
        return self.read.read()


@dataclass(frozen=True)
class PublishedNativeTranscriptReadWork(NativeTranscriptReadWork):
    page: TranscriptPage

    def prepare(self) -> TranscriptPage:
        if not self.read.content_current():
            raise StaleRevision("Published transcript inputs changed before admission")
        return self.page


class TranscriptReadDelivery(ABC):
    @abstractmethod
    async def deliver(self, work: NativeTranscriptReadWork) -> TranscriptPage: ...

    def with_runtime(self, runtime: PreparationRuntime) -> TranscriptReadDelivery:
        return PreparedTranscriptReadDelivery(runtime)


class DirectTranscriptReadDelivery(TranscriptReadDelivery):
    """An operational Agent can read before an application is attached."""

    async def deliver(self, work):
        return await asyncio.to_thread(work.prepare)


class PreparedTranscriptReadDelivery(TranscriptReadDelivery):
    """Use the application's existing globally bounded worker/cache owner."""

    def __init__(self, runtime: PreparationRuntime):
        self.runtime = runtime

    async def deliver(self, work):
        return await self.runtime.submit(work)

    def with_runtime(self, runtime):
        return self if self.runtime is runtime else super().with_runtime(runtime)


class CoordinationTranscriptReader:
    """One read-side Comms service, shared by transcript/status/owner requests."""

    def __init__(self, controller):
        self.controller = controller
        self._reader = None
        self._root = None
        self._lock = asyncio.Lock()
        self.delivery: TranscriptReadDelivery = DirectTranscriptReadDelivery()

    def prepare_with(self, runtime: PreparationRuntime) -> None:
        delivery = self.delivery.with_runtime(runtime)
        if delivery is not self.delivery:
            self.delivery = delivery
            # First application attachment adopts its canonical shared Comms
            # service. Ordinary tab returns keep that same service and budget.
            self._reader = self._root = None

    @asynccontextmanager
    async def bind(self, root: str):
        async with self._lock:
            if self._reader is None or self._root != root:
                from toad.app import ToadApp
                app = self.controller.app
                shared = app.coordination_access.observed_service if isinstance(app, ToadApp) else None
                self._reader = (shared if shared is not None and shared.root == Path(root).expanduser()
                                else await asyncio.to_thread(wire, root))
                self._root = root
            reader = self._reader
        # The lock owns service initialization/replacement, not projections.
        # Each caller retains this exact root service; its canonical stores own
        # read transactions and the Agent fences publication after awaits.
        yield reader

    async def publication(self, update: TranscriptSnapshotUpdate) -> TranscriptSnapshotUpdate:
        identity = update.identity
        async with self.bind(identity.root) as reader:
            read = TranscriptRead(reader.transcripts, identity)
        try:
            page = await self.delivery.deliver(PublishedNativeTranscriptReadWork(read, update.page))
        except StaleRevision:
            return await self.snapshot(identity.root, identity.requested_name,
                before=identity.before, after=identity.after, through=identity.through)
        if not await asyncio.to_thread(read.content_current):
            return await self.snapshot(identity.root, identity.requested_name,
                before=identity.before, after=identity.after, through=identity.through)
        return TranscriptSnapshotUpdate(page, identity)

    async def notifications(self, root, references):
        async with self.bind(root) as reader:
            return await asyncio.to_thread(reader.views.message_notifications_for_references, references)

    async def page(self, root, thread, *, before=None, after=None, through=None,
                   read_identity: TranscriptReadIdentity | None = None):
        snapshot = await self.snapshot(root, thread, before=before, after=after, through=through,
                                       read_identity=read_identity)
        return snapshot.page

    async def snapshot(self, root, thread, *, before=None, after=None, through=None,
                       read_identity: TranscriptReadIdentity | None = None):
        async with self.bind(root) as reader:
            if read_identity is None:
                request = partial(reader.transcripts.capture_page_read, thread)
            else:
                request = partial(reader.transcripts.bind_page_read, thread, read_identity)
            read = await asyncio.to_thread(request, before=before, after=after, through=through)
        page = await self.delivery.deliver(NativeTranscriptReadWork(read))
        # The preparation cache may supply an earlier result. Its original
        # content witness still has to admit it; annotations refresh separately.
        if not await asyncio.to_thread(read.content_current):
            raise StaleRevision("Transcript content changed before publication")
        return TranscriptSnapshotUpdate(page, read.identity)
