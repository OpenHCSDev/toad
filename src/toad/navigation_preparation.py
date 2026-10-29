"""Bounded route discovery without accessing widgets from a reader thread."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from agent_comms.coordination_errors import Refused
from agent_comms.comms import Comms
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.registry_document import RegistrySnapshot
from agent_comms.session_load import ExistingSessionLoadPlan
from agent_comms.thread_execution import ConversationPreparation
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.threads import Thread
from agent_comms.repo import Checkout

from toad.owner_preparation import ExistingOwnerPlan
from toad.session_tracker import CommsViewKey
from toad.tab_identity import SessionTabIdentity

ResultT = TypeVar("ResultT")

if TYPE_CHECKING:
    from toad.navigation_target import HistoryRouted
    from toad.thread_navigation import ThreadNavigator, ThreadOrigin


class NavigationRequest(ABC, Generic[ResultT]):
    @abstractmethod
    def read(self) -> ResultT:
        """Resolve authoritative metadata on a reader thread."""


@dataclass(frozen=True)
class CommsNavigation:
    key: CommsViewKey
    owner_root: str | None
    participants: tuple[ThreadIncarnation, ...]


@dataclass(frozen=True)
class CommsNavigationRequest(NavigationRequest[CommsNavigation]):
    comms: Comms
    owner_mode: str
    me: str
    route: HistoryRouted
    owner_root: str | None

    def read(self) -> CommsNavigation:
        comms = self.comms
        root = comms.root
        resolved = self.route.prepare(comms, self.me)
        owner_root = self.owner_root
        if owner_root is not None and Path(owner_root).expanduser().resolve() != root:
            owner_root = None
        return CommsNavigation(
            CommsViewKey(str(root), self.owner_mode, resolved.conversation),
            owner_root,
            resolved.conversation.threads_needed(
                comms.registry.snapshot(), resolved.viewer
            ),
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
    project: Checkout

    async def open(self, opening: ThreadOpening) -> str:
        return await opening.navigator.mount(self, opening)

    def bind(self, screen) -> None:
        """A saved conversation does not authorize starting its stopped owner."""
        screen.use_mailbox()

    def launch_screen(self, app):
        """A named launch retains the same acquired identity as a sidebar open."""
        from toad.screens.main import MainScreen

        screen = MainScreen.from_thread(
            self.project,
            self.root,
            self.thread.incarnation,
            app.agent_binding,
        )
        self.bind(screen)
        return screen


class ExternalThreadNavigation(ThreadNavigation):
    def bind(self, screen) -> None:
        from toad.session_presentation import MailboxSessionSources

        super().bind(screen)
        screen.presentation.sources = MailboxSessionSources()


@dataclass(frozen=True)
class NativeThreadNavigation(ThreadNavigation):
    plan: ExistingSessionLoadPlan

    def bind(self, screen) -> None:
        screen.presentation.sources.load_plan = self.plan


@dataclass(frozen=True)
class ExistingThreadNavigation(ThreadNavigation):
    existing: OpenThread

    async def open(self, opening: ThreadOpening) -> str:
        navigator = opening.navigator
        source = navigator.app.session_navigation.source(self.existing.mode)
        if source is not None:
            if (source.coordination_root, source.thread_identity.thread_name()) == (
                self.existing.root,
                self.existing.name,
            ):
                await navigator.app.session_navigation.close_many((opening.view.id,))
                await navigator.app.select_session(self.existing.mode)
        # An obsolete open-view identity must never manufacture a duplicate.
        return navigator.app.selected_mode


@dataclass(frozen=True)
class ThreadNavigationRequest(NavigationRequest[ThreadNavigation]):
    comms: Comms
    target: str
    project: Checkout
    open_threads: tuple[OpenThread, ...]

    @property
    def root(self) -> str:
        return str(self.comms.root)

    def read(self) -> ThreadNavigation:
        snapshot = self.comms.registry.snapshot()
        thread = snapshot.require(self.target)
        project = thread.worktree
        existing = next(
            (
                view
                for view in self.open_threads
                if view.root == self.root
                and snapshot.canonical_name(view.name) == thread.name
            ),
            None,
        )
        if existing is not None:
            return ExistingThreadNavigation(self.root, thread, project, existing)
        return thread.execution.prepare_conversation(
            ThreadConversationPreparation(self.root, thread, project, snapshot)
        )


@dataclass(frozen=True)
class ThreadConversationPreparation(ConversationPreparation):
    root: str
    thread: Thread
    project: Checkout
    snapshot: RegistrySnapshot

    def external(self) -> ThreadNavigation:
        return ExternalThreadNavigation(self.root, self.thread, self.project)

    def native(self) -> ThreadNavigation:
        binding = self.thread.execution.owner_binding(self.snapshot, self.thread)
        plan = ExistingOwnerPlan.from_binding(binding)
        if not plan.available:
            return ThreadNavigation(self.root, self.thread, self.project)
        return NativeThreadNavigation(
            self.root, self.thread, self.project, plan.require_plan()
        )


class ThreadOpening:
    """The actual unfinished task owns completion and survives one waiter."""

    def __init__(
        self,
        navigator: ThreadNavigator,
        owner_mode: str,
        request: ThreadNavigationRequest,
        origin: ThreadOrigin,
        identity: SessionTabIdentity,
    ) -> None:
        from toad.screens.main import MainScreen

        self.navigator, self.owner_mode = navigator, owner_mode
        self.request, self.origin = request, origin
        self.identity = identity
        self.view = MainScreen.opening(request, origin, navigator.app)
        self.task = asyncio.create_task(self.run(), name="thread-navigation")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.owner_mode, self.request.root, self.request.target

    async def run(self) -> str:
        from agent_comms.route_selection import root_is_current

        navigator = self.navigator
        try:
            await navigator.mount_loading(self)
            prepared = await navigator.app.navigation_reader.read(self.request)
            if prepared is None:
                await navigator.app.session_navigation.close_many((self.view.id,))
                return navigator.app.selected_mode
            if (
                navigator.app.workspace_sessions.views.get(self.view.id)
                is not self.view
            ):
                return navigator.app.selected_mode
            if not await navigator.app.preparation.run_thread(
                root_is_current, self.request.root
            ):
                raise RuntimeError("The thread's bus route changed while opening")
            return await prepared.open(self)
        except Refused as error:
            self.view.opening_failed(error)
            return navigator.app.selected_mode
        finally:
            navigator.finished(self)


class NavigationReader:
    """Latest intent wins; at most two real metadata reads run concurrently.

    A cancelled UI waiter cannot free the work slot of a thread still
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
            pending = asyncio.create_task(
                asyncio.to_thread(request.read), name="navigation-read"
            )
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
