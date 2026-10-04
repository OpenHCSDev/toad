"""Bounded route discovery without accessing widgets from a reader thread."""

from __future__ import annotations
from toad.navigation_target import NavigationContext

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from agent_comms.threads import Thread
from agent_comms.comms import Comms, wire
from agent_comms.declared_family import DeclaredFamily
from agent_comms.thread_execution import ConversationPreparation

from toad.session_tracker import CommsViewKey
from toad.conversation_kind import ConversationKind

ResultT = TypeVar("ResultT")

if TYPE_CHECKING:
    from toad.thread_navigation import ThreadNavigator, ThreadOrigin


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
    kind: type[ConversationKind]
    recovery_root: str | None

    def read(self) -> CommsNavigation:
        root = Path(self.root).expanduser().resolve()
        comms = wire(root)
        me, target = self.kind.resolve(comms, self.me, self.target)
        recovery_root = self.recovery_root
        if recovery_root is not None and Path(recovery_root).expanduser().resolve() != root:
            recovery_root = None
        return CommsNavigation(
            CommsViewKey(str(root), self.owner_mode, me, self.kind, target),
            recovery_root,
        )


@dataclass(frozen=True)
class OpenThread:
    mode: str
    root: str
    name: str


@dataclass(frozen=True)
class ThreadNavigation(DeclaredFamily, affix="ThreadNavigation"):
    root: str
    thread: Thread
    project: Path

    attachable = False

    @abstractmethod
    async def open(self, opening: ThreadOpening) -> str: ...


class ExternalThreadNavigation(ThreadNavigation):
    async def open(self, opening: ThreadOpening) -> str:
        from toad.navigation_target import DirectTarget

        return await DirectTarget(self.thread.name).open(NavigationContext(
            opening.navigator.app, opening.owner_mode, opening.request.project,
            opening.origin.source._comms_thread))


class StoppedThreadNavigation(ExternalThreadNavigation):
    async def open(self, opening: ThreadOpening) -> str:
        app = opening.navigator.app
        app.notify(f"@{self.thread.name} is stopped; choose Start thread to resume it",
                   title="Thread view")
        return await super().open(opening)


class NativeThreadNavigation(ThreadNavigation):
    attachable = True

    async def open(self, opening: ThreadOpening) -> str:
        return await opening.navigator.mount(self, opening)


@dataclass(frozen=True)
class ExistingThreadNavigation(NativeThreadNavigation):
    existing: OpenThread

    async def open(self, opening: ThreadOpening) -> str:
        navigator = opening.navigator
        source = navigator.app.session_navigation.source(self.existing.mode)
        if source is not None:
            if (source.coordination_root, source._comms_thread) == (self.existing.root, self.existing.name):
                await navigator.app.select_session(self.existing.mode)
        # An obsolete open-view identity must never manufacture a duplicate.
        return navigator.app.selected_mode


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
        project = Path(thread.worktree)
        if not project.is_dir():
            project = self.project
        return thread.execution.prepare_conversation(
            ThreadConversationPreparation(str(root), thread, project, comms, self.open_threads))


@dataclass(frozen=True)
class ThreadConversationPreparation(ConversationPreparation):
    root: str
    thread: Thread
    project: Path
    comms: Comms
    open_threads: tuple[OpenThread, ...]

    def external(self) -> ThreadNavigation:
        return ExternalThreadNavigation(self.root, self.thread, self.project)

    def native(self) -> ThreadNavigation:
        existing = next((view for view in self.open_threads
                         if view.root == self.root
                         and self.comms.registry.canonical_name(view.name) == self.thread.name), None)
        if not self.comms.registry.status(self.thread.name).active:
            return StoppedThreadNavigation(self.root, self.thread, self.project)
        if existing is not None:
            return ExistingThreadNavigation(self.root, self.thread, self.project, existing)
        return NativeThreadNavigation(self.root, self.thread, self.project)


class ThreadOpening:
    """The actual unfinished task owns completion and survives one waiter."""

    def __init__(self, navigator: ThreadNavigator, owner_mode: str,
                 request: ThreadNavigationRequest, origin: ThreadOrigin) -> None:
        self.navigator, self.owner_mode = navigator, owner_mode
        self.request, self.origin = request, origin
        self.task = asyncio.create_task(self.run(), name="thread-navigation")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.owner_mode, self.request.root, self.request.target

    async def run(self) -> str:
        from toad.comms_root import root_is_current

        navigator = self.navigator
        try:
            prepared = await navigator.app.navigation_reader.read(self.request)
            if prepared is None:
                return navigator.app.selected_mode
            if not self.origin.current(navigator, self.owner_mode):
                return navigator.app.selected_mode
            if not root_is_current(self.request.root):
                return navigator.app.selected_mode
            return await prepared.open(self)
        except Exception as error:
            navigator.app.notify(str(error), title="Thread unavailable", severity="error")
            return navigator.app.selected_mode
        finally:
            navigator.finished(self)


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
