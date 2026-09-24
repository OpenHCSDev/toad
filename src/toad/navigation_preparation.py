"""Bounded route discovery without accessing widgets from a reader thread."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar, cast

from agent_comms import Thread, wire

from toad.session_tracker import CommsViewKey
from toad.channel_preparation import HistoryKind

ResultT = TypeVar("ResultT")


class NavigationRequest(ABC, Generic[ResultT]):
    @abstractmethod
    def read(self) -> ResultT:
        """Resolve authoritative metadata on a reader thread."""


@dataclass(frozen=True)
class CommsNavigation:
    key: CommsViewKey
    recovery_root: str | None


@dataclass(frozen=True)
class CommsNavigationRequest(NavigationRequest[CommsNavigation]):
    root: str
    owner_mode: str
    me: str
    target: str
    kind: HistoryKind
    recovery_root: str | None

    def read(self) -> CommsNavigation:
        root = Path(self.root).expanduser().resolve()
        comms = wire(root)
        me = self.me
        if self.kind is HistoryKind.DIRECT:
            me = comms.registry.require(me).name
            target = comms.registry.require(self.target).name
        else:
            # Local sessions can browse channels before an executor registers.
            if me in comms.registry:
                me = comms.registry.require(me).name
            target = comms.channel_catalog.resolve(self.target).name
        recovery_root = self.recovery_root
        if recovery_root is not None and Path(recovery_root).expanduser().resolve() != root:
            recovery_root = None
        return CommsNavigation(
            CommsViewKey(str(root), self.owner_mode, me, self.kind.value, target), recovery_root,
        )


@dataclass(frozen=True)
class OpenThread:
    mode: str
    root: str
    name: str


@dataclass(frozen=True)
class ThreadNavigation:
    root: str
    thread: Thread
    active: bool
    resumable: bool
    project: Path
    existing: OpenThread | None


@dataclass(frozen=True)
class ThreadNavigationRequest(NavigationRequest[ThreadNavigation]):
    root: str
    target: str
    project: Path
    open_threads: tuple[OpenThread, ...]

    def read(self) -> ThreadNavigation:
        root = Path(self.root).expanduser().resolve()
        comms = wire(root)
        thread = comms.registry.require(self.target)
        active = comms.registry.status(thread.name).active
        persisted = bool(thread.session_file and Path(thread.session_file).is_file())
        attachable = thread.pid > 0 and comms._process_alive(thread.pid)
        project = Path(thread.worktree)
        if not project.is_dir():
            project = self.project
        existing = next((view for view in self.open_threads
                         if view.root == str(root)
                         and comms.registry.canonical_name(view.name) == thread.name), None)
        return ThreadNavigation(str(root), thread, active, persisted or attachable, project, existing)


class NavigationReader:
    """Latest intent wins; at most two real metadata reads run concurrently.

    A cancelled UI waiter cannot free the admission slot of a thread still
    waiting on a filesystem/core lock. Superseded queued requests never read.
    """

    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(2)
        self._pending: set[asyncio.Task[object]] = set()
        self._generation = 0
        self._closed = False

    def invalidate(self) -> None:
        self._generation += 1

    async def read(self, request: NavigationRequest[ResultT]) -> ResultT | None:
        self.invalidate()
        generation = self._generation
        await self._slots.acquire()
        if self._closed or generation != self._generation:
            self._slots.release()
            return None
        try:
            pending = asyncio.create_task(asyncio.to_thread(request.read), name="navigation-read")
        except BaseException:
            self._slots.release()
            raise
        tracked = cast(asyncio.Task[object], pending)
        self._pending.add(tracked)
        tracked.add_done_callback(self._finished)
        await asyncio.wait((pending,))
        if self._closed or generation != self._generation:
            return None
        return pending.result()

    def _finished(self, task: asyncio.Task[object]) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()
        self._slots.release()

    async def aclose(self) -> None:
        self._closed = True
        self.invalidate()
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
