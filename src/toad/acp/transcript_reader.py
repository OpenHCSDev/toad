"""Operational read custody; rich pager retirement does not discard source reuse."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from agent_comms.comms import wire
from agent_comms.coordination_errors import StaleRevision
from agent_comms.transcripts import TranscriptRead, TranscriptPage

from toad.work_preparation import (
    ContentAddressedWork, SerializedWork, ThreadWork, PreparationRuntime,
)


@dataclass(frozen=True)
class NativeTranscriptReadWork(ContentAddressedWork[TranscriptPage],
                               SerializedWork[TranscriptPage], ThreadWork[TranscriptPage]):
    read: TranscriptRead

    @property
    def inputs(self):
        return self.read.identity

    def prepare(self) -> TranscriptPage:
        return self.read.read()


class TranscriptReadDelivery(ABC):
    @abstractmethod
    async def deliver(self, read: TranscriptRead) -> TranscriptPage: ...

    def with_runtime(self, runtime: PreparationRuntime) -> TranscriptReadDelivery:
        return PreparedTranscriptReadDelivery(runtime)


class DirectTranscriptReadDelivery(TranscriptReadDelivery):
    """An operational Agent can read before an application is attached."""

    async def deliver(self, read):
        return await asyncio.to_thread(read.read)


class PreparedTranscriptReadDelivery(TranscriptReadDelivery):
    """Use the application's existing globally bounded worker/cache owner."""

    def __init__(self, runtime: PreparationRuntime):
        self.runtime = runtime

    async def deliver(self, read):
        return await self.runtime.submit(NativeTranscriptReadWork(read))

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
            yield self._reader

    async def page(self, root, thread, *, before=None, after=None, through=None):
        while True:
            async with self.bind(root) as reader:
                read = await asyncio.to_thread(
                    reader.transcripts.capture_page_read, thread,
                    before=before, after=after, through=through,
                )
            try:
                page = await self.delivery.deliver(read)
            except StaleRevision:
                # A changed canonical source is a new work identity. No old
                # result is promoted just because it finished before its copy.
                continue
            if await asyncio.to_thread(read.current):
                return page
