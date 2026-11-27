"""Toad's cached access to the Comms service of the current route.

Core owns route selection and guarded writes (``agent_comms.installer.route_selection``)
and observes its own stores (``agent_comms.ui_model.observation``). This owner
caches the service it opened for one selection, runs one observation process
for it, tells that process what the open views show, and applies its results:
the sidebar model, open threads' status rows and their presentations. Views'
transcript reads and owner reads (goal snapshot, input delivery) are requests
to that process, awaited here.
"""

from __future__ import annotations

import asyncio
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import ClassVar, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.messaging.message_files import FileUpload
from agent_comms.errors import RouteChangedError
from agent_comms.execution.child_process import (
    Platform,
    WorkerStart,
    join_retirement,
)
from agent_comms.execution.remote_core_process import ProcessRemoteCoreAccess
from agent_comms.team.team_board_selection import NamedTeamBoards, TeamBoardSelection
from agent_comms.execution.transcript_sources import TranscriptCursor
from agent_comms.installer.active_route import CommsRoute
from agent_comms.installer.route_selection import RouteSelection
from agent_comms.messaging.channel_targets import NamedTarget
from agent_comms.messaging.display_references import (
    PendingReferences,
    ReferenceContext,
    RegistryReferenceSource,
    UnavailableReferences,
)
from agent_comms.messaging.historical_views import HistoricalSenders, HistoricalThread
from agent_comms.messaging.message_notification import MessageNotification
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.messaging.revision_views import (
    ExternalTranscriptsView,
    RegistrationsView,
    StatusView,
)
from agent_comms.presentation import NoRevision, ReadState
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.registry_document import (
    ProjectThreadSelection,
    RegistrySnapshot,
)
from agent_comms.registry.threads import Thread
from agent_comms.transport.request import CoreAccess, ToolRequest
from agent_comms.transport.tools.sidebar import (
    CommsHistoricalThreadsTool,
    CommsMarkThreadViewReadTool,
    CommsRegistryTool,
    CommsServedRootTool,
    CommsSessionThreadTool,
    CommsUserSendTool,
)
from agent_comms.ui_model.observation import (
    AwaitedRead,
    NotificationsObserved,
    NotificationsReload,
    NotificationsUnreadable,
    ObservationEnded,
    ObservationProcess,
    ObservationSource,
    Observed,
    ObserveNotifications,
    ObserveSidebar,
    ObserveTeamHud,
    ObserveThreads,
    ObserveViews,
    ReadNotifications,
    RevisionObserved,
    SidebarObserved,
    SidebarPreparing,
    SidebarUnreadable,
    StopSidebar,
    StopTeamHud,
    TeamHudObserved,
    TeamHudUnreadable,
    ThreadsObserved,
    ViewsRetired,
)
from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation
from agent_comms.ui_model.status import OpenThreadStatus
from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.client.agent_processes import AgentProcesses, NoAgentProcesses
from toad.client.transcript_reader import CoordinationTranscriptReader
from toad.client.bus_selection import BusChoice, ProfileArgument
from toad.client.host import CommsHost
from toad.client.subscribers import NotificationSubscriber, SidebarSubscriber
from toad.client.context_reads import ContextReads
from toad.core.events import (
    CoordinationObserved,
    CoreEventStream,
    ExternalTranscriptChanged,
    LinkContextChanged,
    ObservedServiceChanged,
    OpenTabsChanged,
    SidebarPresented,
    TeamHudChanged,
    TeamHudFailed,
    ThreadInterestUpdate,
    ThreadRowsChanged,
)
from toad.client.db import UNSCOPED_TABS, TabScope
from toad.client.notification_status import (
    CheckedNotifications,
    NotificationStatus,
    UncheckedNotifications,
)
from toad.client.referenced_core import ReferencedCore
from toad.client.resource_release import AsyncResourceRelease, ResourceRelease
from toad.client.session_projection import SessionCollection, SessionProjection
from toad.client.thread_comms_source import RelationshipReads

T = TypeVar("T")

ROUTE_CHECK_SECONDS = 1.0


class CapturedSource(ABC):
    """The Core a UI action read its source from, held until the action writes or redraws.
    Each connection captures it its own way; the action only confirms it."""

    @property
    @abstractmethod
    def root(self) -> Path:
        """The root Core serves, as this capture holds it."""

    @abstractmethod
    def confirm(self, access: CoordinationAccess) -> None:
        """Refuse when what was captured is no longer what this UI observes."""

    @abstractmethod
    def serves(self, root: str | Path) -> bool:
        """Whether ``root`` names the captured root."""

    @abstractmethod
    def observed(self, access: CoordinationAccess) -> Observing:
        """The observation this capture reads through, confirmed still to be it."""


@dataclass(frozen=True)
class SelectedRoute(CapturedSource):
    """In process: the route selection the action read under, resolved on this machine."""

    selection: RouteSelection

    @property
    def root(self) -> Path:
        return self.selection.root

    def confirm(self, access: CoordinationAccess) -> None:
        access.confirm_route(self.selection)

    def serves(self, root: str | Path) -> bool:
        return Path(root).expanduser().resolve() == self.root

    def observed(self, access: CoordinationAccess) -> Observing:
        return access.require(self.selection)


@dataclass(frozen=True)
class CurrentObservation(CapturedSource):
    """Across the connector: the observation the action read through. It is still the
    capture while it is the current one; its root is Core's spelling, never this machine's."""

    observing: Observing

    @property
    def root(self) -> Path:
        return self.observing.root

    def confirm(self, access: CoordinationAccess) -> None:
        if not self.observing.is_current():
            raise RouteChangedError("The connector's observation changed before the operation")

    def serves(self, root: str | Path) -> bool:
        return self.observing.observes(root)

    def observed(self, access: CoordinationAccess) -> Observing:
        self.confirm(access)
        return self.observing


class CoreConnection(ABC):
    """The selected Core transport: it owns its route selection and opens its observation."""

    helper_start: ClassVar[WorkerStart] = Platform.current().worker_start()
    """How this launch gets its worker processes (render workers, a remote Core's read
    workers): the platform's member, fresh interpreters on a desktop and forks of the
    application on Android."""

    agent_processes: ClassVar[AgentProcesses]
    """Whether an agent process starts under this connection: only beside a local route
    (`LocalCoreConnection`, in `toad.client.local_connection`)."""

    def open_access(self, app: CommsHost) -> CoordinationAccess:
        return CoordinationAccess(app, self)

    @abstractmethod
    def chosen(self, arguments: list[str]) -> CoreConnection:
        """The connection a bus the owner chose names, read by this connection's kind."""

    def offered_buses(self, now: float) -> tuple[BusChoice, ...]:
        """Buses this connection kind can open without asking the tailnet (remote-only
        launches list held remote profiles; `LocalCoreConnection` also includes `LocalBus`)."""
        return BusChoice.held(now)

    def close(self) -> None:
        """Release connection-owned work after its observations and reads end."""

    def prewarm(self) -> None:
        """Walk local Core storage declarations when this connection reads them on disk.
        A remote connection talks to Core over HTTPS/WebSocket and loads no local stores."""

    @property
    @abstractmethod
    def location(self) -> str:
        """Where this connection's Core is, as shown to the owner."""

    def tab_scopes(self) -> tuple[TabScope, ...]:
        """The saved tabs this connection owns, written under the first: its Core's location."""
        return (TabScope(self.location),)

    @abstractmethod
    def route_selection(self) -> RouteSelection: ...

    @abstractmethod
    def open_selected(self, access: CoordinationAccess, selected: RouteSelection) -> Observing:
        """Open Core for ``selected`` and observe it. Only a connection that selects routes
        opens one; any other refuses as its ``route_selection`` does."""

    @abstractmethod
    def observation_source(self, route: CommsRoute) -> ObservationSource:
        """What serves this connection's observation of ``route``."""

    @abstractmethod
    def capture(self, access: CoordinationAccess, source: str | Path) -> CapturedSource:
        """The source a UI action reads under, refused when it is not this Core's."""

    @abstractmethod
    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """This connection's current observation, or the error that refuses it."""

    def resume_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """Re-verify or reopen this connection's observation after the app resumes from
        suspension. Local routes check their route selection; remote connections recycle
        kept sockets and replace a possibly half-open observation."""
        return self.open_current(access)

    @abstractmethod
    def holds(self, access: CoordinationAccess, source: str | Path) -> bool:
        """Whether ``source`` still belongs to what this connection currently observes."""

    async def holds_async(self, runtime, access: CoordinationAccess, source: str | Path) -> bool:
        """Whether ``source`` still belongs to this connection: local routes check disk on a
        worker thread, while remote connections read their in-memory observation directly."""
        return await runtime.run_thread(self.holds, access, source)

    @abstractmethod
    def observing(self, access: CoordinationAccess, source: str | Path) -> Observing:
        """The observation serving ``source``, or the refusal that it is not this Core's."""


@dataclass(frozen=True)
class RemoteCoreConnection(ProfileArgument, ProcessRemoteCoreAccess, CoreConnection):
    """The owner's UI profile is the remote connection: Core answers through the connector.

    Its reads and their replies' decoding run in worker processes on every platform, so the
    UI's interpreter stays free for frames."""

    agent_processes: ClassVar[AgentProcesses] = NoAgentProcesses()

    @classmethod
    def startup(cls, arguments: list[str]) -> RemoteCoreConnection:
        index = arguments.index(cls.argument)
        if index + 1 == len(arguments):
            raise ValueError(f"{cls.argument} requires a UI profile path")
        connection = cls.read(Path(arguments[index + 1]))
        del arguments[index : index + 2]
        return connection

    @property
    def location(self) -> str:
        return str(self.endpoint.url)

    def chosen(self, arguments: list[str]) -> RemoteCoreConnection:
        """A chosen bus is read by this same member."""
        return type(self).startup(arguments)

    def route_selection(self) -> RouteSelection:
        raise RuntimeError(
            f"{self.endpoint.url} answers Core requests; local route selection does not apply")

    def open_selected(self, access: CoordinationAccess, selected: RouteSelection) -> Observing:
        raise RuntimeError(
            f"{self.endpoint.url} answers Core requests; it opens no local route")

    def observation_source(self, route: CommsRoute) -> ObservationSource:
        """The connector serves this UI's observation; it is the source."""
        return self

    def capture(self, access: CoordinationAccess, source: str | Path) -> CurrentObservation:
        return CurrentObservation(self.observing(access, source))

    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """The current observation through this connector; the observation decides whether
        it already is one."""
        return access.observation.through(self, access)

    def resume_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """After Android suspension or a network switch, drop kept HTTP sockets (which may
        be half-open on a dead local IP) and ask the observation to re-establish itself."""
        self.reset_connections()
        return access.observation.resumed_through(self, access)

    def holds(self, access: CoordinationAccess, source: str | Path) -> bool:
        """The root the connector's Core serves, as the current observation holds it."""
        return access.observation.observed().observes(source)

    async def holds_async(self, runtime, access: CoordinationAccess, source: str | Path) -> bool:
        """Remote observation membership is a pure in-memory check; avoid spawning a worker
        thread and ~10 qasync timers per scroll/read check."""
        return self.holds(access, source)

    def observing(self, access: CoordinationAccess, source: str | Path) -> Observing:
        """The current observation through the connector, when it serves ``source``."""
        return access.observation.observed().serving(source)

    def observe(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """Ask the connector's Core which root it serves, then observe it there."""
        try:
            served = self.call(CommsServedRootTool())
        except (OSError, ValueError, RuntimeError) as error:
            return access.observation.failed(error, UnselectedRoute())
        return access.observe_remote(self, Path(served.root))


@dataclass(frozen=True)
class UnselectedRoute:
    """Route capture failed before a validated selection existed."""


@dataclass
class ObservationRetry:
    """When a lost observation may open again: one owner for the whole outage.

    Each loss in a row doubles the wait, from FIRST up to LONGEST seconds; the first result
    an opened observation receives ends the outage, so the next loss waits FIRST again. The
    route check (once a second) is what reopens. Until the retry is due, reads and interest
    changes see the failure instead of opening a new connection each, which made a Core that
    closes every observation flash ConnectorObserverClosed on every call.
    """

    FIRST: ClassVar[float] = 1.0
    LONGEST: ClassVar[float] = 30.0
    losses: int = 0
    due: float = 0.0
    # When the last result reached the UI (monotonic), so an outage can say how long the UI
    # had gone without one: a relay that ends because its reader took nothing for its write
    # deadline reads differently from a connector that went away.
    last_arrival: float | None = None

    def lost(self, now: float) -> None:
        self.losses += 1
        self.due = now + min(self.FIRST * 2 ** min(self.losses - 1, 16), self.LONGEST)

    def began(self) -> bool:
        """This loss started the outage: the one the reader is told about."""
        return self.losses == 1

    def waiting(self, now: float) -> bool:
        return now < self.due

    def recovered(self) -> None:
        self.losses, self.due = 0, 0.0

    def arrived(self, now: float) -> None:
        """A result reached the UI: the outage, if any, is over."""
        self.recovered()
        self.last_arrival = now

    def quiet_note(self, now: float) -> str:
        """How long before ``now`` the UI last received a result, for the outage's report."""
        if self.last_arrival is None:
            return "No observation result had reached the UI yet."
        return f"The last observation result reached the UI {now - self.last_arrival:.1f} s before this."


@dataclass(frozen=True, kw_only=True)
class Observation(ABC):
    access: CoordinationAccess = field(compare=False)
    subscriptions: ResourceRelease = field(default_factory=ResourceRelease, compare=False)
    # View updates end before the views close; `subscriptions` retires the observation after them.
    updates: ResourceRelease = field(default_factory=ResourceRelease, compare=False)

    def observed(self):
        return self

    @property
    def agent_processes(self) -> AgentProcesses:
        """Whether an agent process may start beside the Core this observation reaches: the
        connection it was opened through decides (a local bus root does, a UI profile does not)."""
        return self.access.connection.agent_processes

    def queue_observing(self) -> Observing:
        raise RouteChangedError("The queue's original Core source is unavailable")

    @abstractmethod
    async def read(self, request: AwaitedRead) -> object: ...

    @abstractmethod
    def subscribe_notifications(
        self, view: NotificationSubscriber, build_read: Callable[[str], ReadNotifications],
    ) -> bool: ...

    def is_current(self) -> bool:
        return self is self.access.observation

    def observes(self, root: str | Path) -> bool:
        return False

    def serving(self, source: str | Path):
        """This observation, when ``source`` is the root it observes."""
        if not self.observes(source):
            raise RouteChangedError(f"{source} is not the root this UI observes")
        return self

    def tab[Navigation](self, entry: SessionProjection[Navigation, Observing], sessions: Navigation):
        return entry.unobserved_tab()

    def tabs(self, sessions: SessionCollection[Observing]):
        return {entry.identity: self.tab(entry, sessions) for entry in sessions.members}
    def require(self, access: CoordinationAccess, selected: RouteSelection):
        return access.connection.open_selected(access, selected)

    def through(self, connection: RemoteCoreConnection, access: CoordinationAccess):
        """No observation through ``connection`` is current yet: open one."""
        return connection.observe(access)

    def resumed_through(self, connection: RemoteCoreConnection, access: CoordinationAccess):
        """Re-establish observation through ``connection`` after app suspension."""
        return self.through(connection, access)

    def focus_returned(self, access: CoordinationAccess) -> None:
        """The window regained focus: check whether the route needs attention."""
        access.check_route()
    def references_for(self, root: str) -> ReferenceContext:
        return PendingReferences(root)
    async def current_references(self, access: CoordinationAccess, root: str):
        return access.reference_context(root)

    def failed(self, error: Exception, selected):
        self.access.retry.lost(time.monotonic())
        return self.adopt(FailedObservation(error, selected, access=self.access))

    def adopt[O: Observation](self, observation: O) -> O | Observation:
        """Make ``observation`` current unless it equals this one; it retires with its
        subscriptions."""
        if observation == self:
            return self
        observation.subscriptions.callback(observation.retire, self.access)
        self.access.observation = observation
        self.access.app.running_loop.call_soon_threadsafe(observation.attach, self.access, self)
        return observation

    def stop_updates(self) -> Observation:
        self.updates.close()
        return self

    def retire(self, access: CoordinationAccess) -> None:
        """An observation without a process has nothing to retire."""

    def pending_notification_views(self) -> tuple[NotificationSubscriber, ...]:
        """Notification subscribers retained while this observation could not subscribe them."""
        return ()

    def rebind_notifications(self, subscribers: tuple[NotificationSubscriber, ...]) -> None:
        """Re-attach active notification views once this observation becomes current."""

    def discard_notification_view(self, view: NotificationSubscriber) -> None:
        """Forget a view that stopped showing notifications before this observation ended."""

    def activate(self, access: CoordinationAccess):
        """The new current observation shows itself in every view following the sidebar,
        hidden or shown: a failure as the failure, a reopened service as its rows. This is
        the only place a view rebinds to a new observation."""
        for view in tuple(access.sidebar_views):
            self.show_sidebar(view)

    def attach(self, access, previous):
        previous.subscriptions.close()
        if not self.is_current():
            self.subscriptions.close()
            return
        waiters, access.sidebar_waiters = access.sidebar_waiters, []
        for _, waiter in waiters:
            if not waiter.done():
                waiter.set_exception(RouteChangedError("Comms service changed before the sidebar was read"))
        subscribers = tuple(dict.fromkeys((
            *access.notification_views, *previous.pending_notification_views(),
        )))
        access.revision = NoRevision()
        access.sidebar_interest = access.sidebar_current = None
        access.team_interest = StopTeamHud()
        access.thread_status.clear()
        access.views_interest = None
        access.notification_views.clear()
        access.notification_known.clear()
        access.notification_interest = ObserveNotifications(frozenset())
        self.activate(access)
        self.rebind_notifications(subscribers)
        access.events.publish(ObservedServiceChanged())


class NotObserving(Observation):
    def observed(self):
        return self.access.open_current()

    async def read(self, request: AwaitedRead) -> object:
        return await self.observed().read(request)

    def subscribe_notifications(
        self, view: NotificationSubscriber, build_read: Callable[[str], ReadNotifications],
    ) -> bool:
        return self.observed().subscribe_notifications(view, build_read)


class ClosedObservation(Observation):
    """The access has closed: nothing is observed, and nothing opens again.

    A frontend's views can still change their interests after the shared shutdown: Qt
    closes the remaining windows as the application ends, and a team page's closeEvent
    stops its heartbeat. Those reached NotObserving, which opened a fresh observation, its
    relay thread and an attach queued onto a loop that was stopping. Here an interest change
    has nothing to change, and a read is refused.
    """

    def through(self, connection: RemoteCoreConnection, access: CoordinationAccess):
        return self

    def focus_returned(self, access: CoordinationAccess) -> None:
        """A closed access never reopens on focus."""

    def require(self, access: CoordinationAccess, selected: RouteSelection):
        return self

    def closed(self) -> RouteChangedError:
        return RouteChangedError("Comms access closed")

    async def read(self, request: AwaitedRead) -> object:
        raise self.closed()

    @property
    def core(self) -> CoreAccess:
        raise self.closed()

    @property
    def sidebar(self):
        raise self.closed()

    def references_for(self, root: str) -> ReferenceContext:
        return UnavailableReferences(root, str(self.closed()))

    def show_sidebar(self, view: SidebarSubscriber[Observing, FailedObservation]) -> None:
        """No view follows a closed access."""

    def observe_sidebar(self, wanted):
        """No observation is left to tell."""

    def observe_notifications(self, wanted: ObserveNotifications):
        """No observation is left to tell."""

    def subscribe_notifications(
        self, view: NotificationSubscriber, build_read: Callable[[str], ReadNotifications],
    ) -> bool:
        """No observation is left to subscribe to."""
        return False

    def thread_interest(self, access: CoordinationAccess):
        """No observation is left to tell."""

    def observe_team(self, wanted: ObserveTeamHud | StopTeamHud):
        """No observation is left to tell."""


@dataclass(frozen=True, eq=False)
class FailedObservation(Observation):
    error: Exception = field(compare=False, repr=False)
    selection: RouteSelection | UnselectedRoute
    failed_notification_views: WeakSet[NotificationSubscriber] = field(
        default_factory=WeakSet, compare=False, repr=False,
    )

    async def read(self, request: AwaitedRead) -> object:
        raise self.error

    def through(self, connection: RemoteCoreConnection, access: CoordinationAccess):
        """Open again once the retry is due; until then this failure is the observation."""
        if access.retry.waiting(time.monotonic()):
            return self
        return super().through(connection, access)

    def focus_returned(self, access: CoordinationAccess) -> None:
        """Returning to a disconnected window clears backoff and reconnects at once."""
        access.retry.recovered()
        access.check_route()

    def require(self, access: CoordinationAccess, selected: RouteSelection):
        """A changed route opens now; the failed one waits for its retry."""
        if selected == self.selection and access.retry.waiting(time.monotonic()):
            return self
        return super().require(access, selected)

    def __eq__(self, other: object) -> bool:
        # Exceptions declare their type, constructor fields and extra state through
        # reconstruction; OSError includes filenames that are absent from args.
        return (isinstance(other, FailedObservation)
                and self.selection == other.selection
                and self.error.__reduce__() == other.error.__reduce__())

    def serving(self, source: str | Path):
        """No root is observed while Core cannot be read: asking for one raises the failure
        that stopped the observation, never the claim that ``source`` is another route's."""
        raise self.error

    @property
    def core(self) -> CoreAccess:
        raise self.error

    @property
    def sidebar(self):
        raise self.error

    async def write_order(self, access: CoordinationAccess, root, request: ToolRequest):
        raise self.error

    def references_for(self, root: str) -> ReferenceContext:
        return UnavailableReferences(root, str(self.error))

    def show_sidebar(self, view: SidebarSubscriber[Observing, FailedObservation]):
        view.bind_failed_observation(self)

    def observe_sidebar(self, wanted):
        """Failure was published on activation; interest changes cannot rebind its views."""

    def observe_notifications(self, wanted: ObserveNotifications):
        for view in tuple(self.access.notification_views):
            view.notifications_failed(self.error)

    def pending_notification_views(self) -> tuple[NotificationSubscriber, ...]:
        return tuple(self.failed_notification_views)

    def rebind_notifications(self, subscribers: tuple[NotificationSubscriber, ...]) -> None:
        for view in subscribers:
            if view not in self.failed_notification_views:
                self.failed_notification_views.add(view)
                view.notifications_failed(self.error)

    def discard_notification_view(self, view: NotificationSubscriber) -> None:
        self.failed_notification_views.discard(view)

    def subscribe_notifications(
        self, view: NotificationSubscriber, build_read: Callable[[str], ReadNotifications],
    ) -> bool:
        """Report the outage once per view without touching a disconnected Core."""
        if view not in self.failed_notification_views:
            self.failed_notification_views.add(view)
            view.notifications_failed(self.error)
        return False

    def thread_interest(self, access: CoordinationAccess):
        if access.retry.began():
            access.app.show_error(self.error, "Thread status unavailable")

    def observe_team(self, wanted: ObserveTeamHud | StopTeamHud):
        self.access.events.publish(TeamHudFailed(self.error))


class RegistryRead:
    """No registry read yet: the first caller starts one."""

    def claim(self, reads: RegistryReads, revision: ReadState) -> RegistryRead:
        return reads.start(revision)

    def answer(self, observation: Observing) -> RegistrySnapshot:
        raise TypeError("An unread registry has no answer; claim a read first")


@dataclass(frozen=True)
class RegistryReadFor(RegistryRead):
    """A read for the registrations the observer announced at ``revision``."""

    revision: ReadState

    def claim(self, reads: RegistryReads, revision: ReadState) -> RegistryRead:
        # No announcement since this read, or one whose registrations did not change.
        if revision is self.revision or not revision.changed_since(RegistrationsView(), self.revision):
            return self
        return super().claim(reads, revision)


@dataclass(frozen=True)
class RegistryReading(RegistryReadFor):
    """A read in flight: every caller for the same registrations waits on this one."""

    answered: Future[RegistrySnapshot] = field(compare=False)

    def answer(self, observation: Observing) -> RegistrySnapshot:
        return self.answered.result()


@dataclass(frozen=True)
class StartedRegistryRead(RegistryRead):
    """The caller that started ``reading`` asks Core, then answers everyone waiting on it."""

    reading: RegistryReading
    reads: RegistryReads

    def answer(self, observation: Observing) -> RegistrySnapshot:
        try:
            snapshot = observation.core.call(CommsRegistryTool())
        except BaseException as error:
            self.reads.settle(self.reading, RegistryRead())
            self.reading.answered.set_exception(error)
            raise
        self.reads.settle(self.reading, RegistryReadAt(self.reading.revision, snapshot))
        self.reading.answered.set_result(snapshot)
        return snapshot


@dataclass(frozen=True)
class RegistryReadAt(RegistryReadFor):
    """The registry as Core answered it while the observer announced ``revision``."""

    registry: RegistrySnapshot

    def answer(self, observation: Observing) -> RegistrySnapshot:
        return self.registry


class RegistryReads:
    """One observation's registry: one read per announced set of registrations.

    Every view, navigation and command asks the observation for the registry. Over a
    remote connection each read is the whole registry (megabytes, seconds), so a caller
    arriving while a read is in flight waits for it instead of starting another.
    """

    def __init__(self) -> None:
        self.latest: RegistryRead = RegistryRead()
        self.lock = threading.Lock()

    def snapshot(self, observation: Observing) -> RegistrySnapshot:
        with self.lock:
            claimed = self.latest.claim(self, observation.access.revision)
        return claimed.answer(observation)

    def start(self, revision: ReadState) -> StartedRegistryRead:
        """Called under the lock: later callers for ``revision`` wait on this read."""
        reading = RegistryReading(revision, Future())
        self.latest = reading
        return StartedRegistryRead(reading, self)

    def settle(self, reading: RegistryReading, settled: RegistryRead) -> None:
        """A finished read replaces itself; a newer read already started keeps its place."""
        with self.lock:
            if self.latest is reading:
                self.latest = settled


@dataclass(frozen=True)
class Observing(Observation, ReferencedCore, RegistryReferenceSource, RelationshipReads, ContextReads):
    """An observation answering through its process; where its Core is belongs to the member."""

    sidebar: SidebarModel
    process: ObservationProcess = field(compare=False)
    registry_reads: RegistryReads = field(default_factory=RegistryReads, compare=False)
    answering: ClassVar[type[AnsweringReads]]

    def registry(self) -> RegistrySnapshot:
        return self.registry_reads.snapshot(self)

    def queue_observing(self) -> Observing:
        if not self.is_current():
            raise RouteChangedError("The queue's original Core source retired")
        return self

    async def read(self, request: AwaitedRead) -> object:
        return await self.process.read(request)

    async def write_order(self, access: CoordinationAccess, root, request: ToolRequest):
        """Store the chosen order on the Core this observation reaches, local or remote."""
        if root is not None and not self.observes(root):
            raise ValueError("Comms route changed before sorting")
        return await access.preparation.run_thread(self.core.call, request)

    @property
    @abstractmethod
    def root(self) -> Path:
        """The bus root this observation's Core serves; root-keyed requests and views key on it."""

    def observes(self, root: str | Path) -> bool:
        """Core's served root as Core spells it; a local member resolves on this machine."""
        return Path(root) == self.root

    def historical_threads(self, senders: HistoricalSenders) -> tuple[HistoricalThread, ...]:
        """The preserved identities attached history sources keep, for every sender or one."""
        return self.core.call(CommsHistoricalThreadsTool(senders=senders)).threads

    @abstractmethod
    def user_identity(self, project: Checkout) -> Thread:
        """The one human sender this UI speaks as."""

    def session_thread(self, project: Path, preferred: str) -> ProjectThreadSelection:
        """The thread an unbound session at ``project`` names; Core's host resolves the path."""
        return self.core.call(CommsSessionThreadTool(project=str(project), preferred=preferred))

    def send_user_message(self, target: NamedTarget, body: str,
                          files: tuple[FileUpload, ...]) -> MessageReference:
        """The owner's input and the files attached to it, published by Core under the
        owner's identity, in process or across the connector; the reference is what the view
        waits to draw."""
        return self.core.call(CommsUserSendTool(target=target.name, body=body, files=files)).message.source

    def mark_thread_read(self, identity, project: Path, through: TranscriptCursor) -> None:
        """Acknowledge, as the owner, what this UI displayed of one thread: Core applies it,
        in process or across the connector."""
        thread = identity.resolve_thread(self, project)
        self.core.call(CommsMarkThreadViewReadTool(thread=thread, through=through))

    def tab[Navigation](self, entry: SessionProjection[Navigation, Observing], sessions: Navigation):
        return entry.tab(sessions, self)

    def show_sidebar(self, view: SidebarSubscriber[Observing, FailedObservation]) -> None:
        if self.is_current():
            view.bind_observation(self)

    @property
    @abstractmethod
    def core(self) -> CoreAccess:
        """Where this UI's requests to the observed Core are answered."""

    @abstractmethod
    def opened_selection(self) -> RouteSelection | UnselectedRoute:
        """The local route this observation was opened for; a remote one has none."""

    def activate(self, access: CoordinationAccess):
        self.process.start_receiving(self.receive, self.receive_failed)
        super().activate(access)
        access.update_sidebar_interest()
        access.update_team_interest()
        self.thread_interest(access)
        self.updates.enter_context(access.app.events.subscribe(OpenTabsChanged, self.views_changed))
        self.subscriptions.enter_context(self.updates)
        self.views_changed()

    def stop_updates(self) -> AnsweringReads:
        """End this observation's updates, then say so to the peer.

        The answering member is what an observation becomes once its interests end, and it is
        reached whether or not the peer is still there to hear it: a goodbye sent through a
        connection the peer already dropped raised `ConnectorObserverClosed` out of
        `stop_updates`, so a network blip escaped `AsyncResourceRelease._raise_errors` and
        killed Toad's own teardown (17 `Terminal_crash` logs, 2026-11-06 02:51).
        """
        super().stop_updates()
        self.process.stop_observing()
        return self.answering(**{item.name: getattr(self, item.name) for item in fields(self)})

    def retire(self, access: CoordinationAccess):
        task = asyncio.create_task(self.process.close())
        access.retiring.add(task)
        task.add_done_callback(access.retiring.discard)

    def receive(self, result: Observed):
        if self.is_current():
            self.access.retry.arrived(time.monotonic())
            self.access.dispatch_sync(result, self)

    def tell(self, wanted) -> None:
        """Tell the peer what this observation's views want.

        A process that has ended answers with its end, and its reader reports that same end
        through ``receive_failed``, which makes the failure current and retries. Raised here
        too, it escaped whichever view changed its interest (an attach queued just before the
        peer closed, a viewport asking for notifications) as a second, uncaught report of one
        closure. As ObservationProcess.stop_observing does, the end stays with its owner.
        """
        try:
            self.process.request(wanted)
        except ObservationEnded:
            pass

    def receive_failed(self, error: Exception):
        """The observation closed: the failure becomes current and retries; the reader is
        told once per outage, not once per reopen that closes again."""
        if self.is_current():
            self.failed(error, self.opened_selection())
            if self.access.retry.began():
                error.add_note(self.access.retry.quiet_note(time.monotonic()))
                self.access.app.report_fatal(error)

    def views_changed(self, event=None, subscription=None):
        access, root = self.access, str(self.root)
        threads = access.app.open_thread_identities(root)
        channels = access.app.open_channel_targets(root)
        request = ObserveViews(frozenset(threads), frozenset(channels))
        if request != access.views_interest:
            access.views_interest = request
            self.tell(request)

    def references_for(self, root: str) -> ReferenceContext:
        return self.sidebar.observation.references_for(root)

    async def current_references(self, access: CoordinationAccess, root: str):
        """Draw with the sidebar's answered names; before it answers, read them from Core."""
        return await access.reference_context(root).settled(self)

    async def registry_references(self, root: str):
        """The registry's and channel catalog's names, read without waiting for a sidebar capture."""
        references = await self.access.preparation.run_thread(self.references)
        return references.at(root)

    def thread_interest(self, access: CoordinationAccess):
        self.tell(ObserveThreads(access.events.observed_threads(str(self.root))))

    def observe_sidebar(self, wanted):
        self.tell(wanted if wanted is not None else StopSidebar())

    def observe_notifications(self, wanted: ObserveNotifications):
        self.tell(wanted)

    def rebind_notifications(self, subscribers: tuple[NotificationSubscriber, ...]) -> None:
        for view in subscribers:
            view.rebind_notifications()

    def subscribe_notifications(
        self, view: NotificationSubscriber, build_read: Callable[[str], ReadNotifications],
    ) -> bool:
        return self.access.show_notifications(view, build_read(str(self.root)))

    def observe_team(self, wanted: ObserveTeamHud | StopTeamHud):
        self.tell(wanted)

class AnsweringReads(Observing):
    """Interests have ended; acquired reads keep their process and release owners. Each
    location's member declares the observation it answers for once interests stop."""

    def __init_subclass__(cls, *, answers_for: type[Observing], **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        answers_for.answering = cls

    def stop_updates(self) -> AnsweringReads:
        return self

    def tell(self, wanted) -> None:
        """Interests have ended; no further interest updates are sent."""

    def views_changed(self, event=None, subscription=None):
        pass


@dataclass(frozen=True)
class RemoteObserving(Observing):
    """Core behind the connector: the connection answers requests, its peer carries observation."""

    connection: RemoteCoreConnection = field(kw_only=True, compare=False)
    served_root: Path = field(kw_only=True)

    @property
    def root(self) -> Path:
        return self.served_root

    def through(self, connection: RemoteCoreConnection, access: CoordinationAccess):
        """This observation already observes through ``connection``; its failure, not a
        repeated request, is what replaces it."""
        return self if self.connection is connection else connection.observe(access)

    def resumed_through(self, connection: RemoteCoreConnection, access: CoordinationAccess):
        """After Android suspension or a network switch, the existing WebSocket may be
        half-open; open a fresh observation instead of waiting on heartbeat timeout."""
        return connection.observe(access)

    def user_identity(self, project: Checkout) -> Thread:
        """Across the connector the user thread is Core's; this machine's checkout claims nothing."""
        return self.registry().user_thread().require(RuntimeError(
            f"{self.connection.location} has no user thread; open a UI on Core's machine first"))

    def opened_selection(self) -> UnselectedRoute:
        return UnselectedRoute()

    @property
    def core(self) -> CoreAccess:
        return self.connection


@dataclass(frozen=True)
class RemoteAnsweringReads(AnsweringReads, RemoteObserving, answers_for=RemoteObserving):
    pass


class CoordinationAccess(MroDispatch):
    """A validated Core route owns cached access, observations and UI write checks."""

    def __init__(self, app: CommsHost, connection: CoreConnection) -> None:
        self.app = app
        self.connection = connection

        self.transcripts = CoordinationTranscriptReader(self)
        self.observation: Observation = NotObserving(access=self)
        self.retry = ObservationRetry()
        self.events = CoreEventStream(self)
        self.revision: ReadState = NoRevision()
        self.route_task: asyncio.Task[None] | None = None
        self.timer = None
        self.opening = threading.RLock()
        self.preparation = app.preparation
        self.retiring: set[asyncio.Task[None]] = set()
        # One status row per open thread, whichever service it was read from.
        self.thread_status = OpenThreadStatus(app.schedule_ui)
        # Views following the current observation's sidebar, hidden or shown, and consumers
        # waiting for current rows. Core's rows are observed while one view shows them.
        self.sidebar_views: WeakSet[SidebarSubscriber[Observing, FailedObservation]] = WeakSet()
        self.reference_views: WeakSet = WeakSet()
        self.sidebar_waiters: list[tuple[ObserveSidebar, asyncio.Future[SidebarObservation]]] = []
        self.sidebar_interest: ObserveSidebar | None = None
        self.sidebar_current: ObserveSidebar | None = None
        self.views_interest: ObserveViews | None = None
        self.notification_views: WeakKeyDictionary[NotificationSubscriber, ReadNotifications] = WeakKeyDictionary()
        # The last answer for each message under each read scope (root, display, source).
        # A scroll changes which messages a view reads, never what is already known.
        self.notification_known: dict[tuple[ReadNotifications, tuple[int, str]], tuple[MessageNotification, ...]] = {}
        self.notification_interest = ObserveNotifications(frozenset())
        # Open team pages; the heartbeat's frames are observed only while one is shown.
        self.team_pages: WeakKeyDictionary[object, TeamBoardSelection] = WeakKeyDictionary()
        self.team_interest: ObserveTeamHud | StopTeamHud = StopTeamHud()

    @property
    def selection(self) -> RouteSelection:
        """The current route resolved from this app's held launch root."""
        return self.connection.route_selection()

    def selected(self, source: str | Path) -> CapturedSource:
        """Capture the source an action reads under and refuse a foreign one."""
        return self.connection.capture(self, source)

    def current(self, source: str | Path) -> bool:
        """Whether a source still belongs to this app's current Core."""
        return self.connection.holds(self, source)

    def observing(self, source: str | Path) -> Observing:
        """The observation serving ``source``: this app's Core, or a refusal that it is not."""
        return self.connection.observing(self, source)

    def open_current(self) -> Observing | FailedObservation:
        """The connection's current observation, or the error that refuses it."""
        with self.opening:
            return self.connection.open_current(self)

    def reopen_current(self) -> Observing | FailedObservation:
        """Re-establish the connection's observation after suspension or network change."""
        with self.opening:
            return self.connection.resume_current(self)

    def confirm(self, captured: CapturedSource) -> None:
        captured.confirm(self)

    def confirm_route(self, selected: RouteSelection) -> None:
        if self.selection != selected:
            raise RouteChangedError("Comms route changed before the operation")

    def require(self, selected: RouteSelection) -> Observing:
        """The service for ``selected``; a new selection opens it and starts its observation."""
        self.confirm_route(selected)
        with self.opening:
            return self.observation.require(self, selected)

    def observe_remote(self, connection: RemoteCoreConnection, root: Path) -> RemoteObserving:
        """Observe the Core behind the connector: its peer carries the observation, and the
        root it serves keys every root-scoped request."""
        with self.opening:
            return self.observation.adopt(RemoteObserving(
                SidebarModel(self.app.schedule_ui), ObservationProcess(connection),
                connection=connection, served_root=root, access=self))

    @handles(RevisionObserved)
    def revision_observed(self, result: RevisionObserved, observed: Observing) -> None:
        previous = self.revision
        self.revision = result.revision
        if result.revision.changed_since(StatusView(), previous):
            self.events.publish(CoordinationObserved(result.revision))
        if result.revision.changed_since(ExternalTranscriptsView(), previous):
            self.events.publish(ExternalTranscriptChanged())

    @handles(TeamHudObserved)
    def team_hud_observed(self, result: TeamHudObserved, observed: Observing) -> None:
        self.events.publish(TeamHudChanged(result.cut))

    @handles(TeamHudUnreadable)
    def team_hud_unreadable(self, result: TeamHudUnreadable, observed: Observing) -> None:
        self.events.publish(TeamHudFailed(result.error))

    @handles(SidebarObserved)
    def sidebar_observed(self, result: SidebarObserved, observed: Observing) -> None:
        if result.request != self.sidebar_interest:
            return  # Read for an interest the views have since changed.
        app = self.app
        notice = observed.sidebar.observation.read_marker_notice()
        modes = app.tab_names
        previous_references = self.reference_context(str(observed.root))
        observed.sidebar.apply(result.snapshot, result.derived)
        self.present_sidebar()
        if previous_references != self.reference_context(str(observed.root)):
            self.events.publish(LinkContextChanged())
        self.sidebar_current = result.request
        result.snapshot.read_marker_notice.notify_if_new(
            notice, lambda text: app.show_warning(text, title="Read positions"))
        if app.tab_names != modes:
            app.events.publish(OpenTabsChanged())
        for waiter in self.take_sidebar_waiters(result.request):
            waiter.set_result(observed.sidebar.observation)

    @handles(SidebarPreparing)
    def sidebar_preparing(self, result: SidebarPreparing, observed: Observing) -> None:
        if result.request != self.sidebar_interest:
            return
        observed.sidebar.observation = result
        self.present_sidebar()

    @handles(SidebarUnreadable)
    def sidebar_unreadable(self, result: SidebarUnreadable, observed: Observing) -> None:
        if result.request != self.sidebar_interest:
            return
        observed.sidebar.clear(result.error)
        self.present_sidebar()
        self.events.publish(LinkContextChanged())
        self.sidebar_current = result.request
        for waiter in self.take_sidebar_waiters(result.request):
            waiter.set_result(observed.sidebar.observation)
        self.app.show_error(result.error, "Sidebar unavailable")

    def present_sidebar(self) -> None:
        """Present the same backend answer to the sidebar and its other views."""
        for view in self.showing_sidebar():
            view.present()
        self.events.publish(SidebarPresented())

    def take_sidebar_waiters(self, answered: ObserveSidebar) -> list[asyncio.Future[SidebarObservation]]:
        """Retire answered reads once, leaving other interests subscribed."""
        remaining, answered_waiters = [], []
        for request, waiter in self.sidebar_waiters:
            if request != answered:
                remaining.append((request, waiter))
            elif not waiter.done():
                answered_waiters.append(waiter)
        self.sidebar_waiters = remaining
        self.update_sidebar_interest()
        return answered_waiters

    @handles(ThreadsObserved)
    def threads_observed(self, result: ThreadsObserved, observed: Observing) -> None:
        self.thread_status.observed(result)
        self.events.publish(ThreadRowsChanged(names=result.changed, root=str(observed.root)))

    @handles(ViewsRetired)
    def views_retired(self, result: ViewsRetired, observed: Observing) -> None:
        self.app.retire_views(observed.root, result.retired)

    def show_notifications(self, view: NotificationSubscriber, read: ReadNotifications) -> bool:
        """Show `read` in `view`; asking again for the read it already shows changes nothing."""
        if self.notification_views.get(view) == read:
            return False
        self.notification_views[view] = read
        if known := self.known_outcomes(read):
            view.notifications_observed(known)
        self._request_interest()
        return True

    @staticmethod
    def notification_scope(read: ReadNotifications) -> ReadNotifications:
        """The read without its messages: root, display cut and source decide an outcome."""
        return replace(read, operation=replace(read.operation, references=()), request_id=0)

    def known_outcomes(self, read: ReadNotifications) -> dict[tuple[int, str], tuple[MessageNotification, ...]]:
        scope = self.notification_scope(read)
        return {key: self.notification_known[scope, key]
                for key in read.keys if (scope, key) in self.notification_known}

    def notification_status(self, read: ReadNotifications, references: tuple[MessageReference, ...]) -> NotificationStatus:
        """The last known status of these messages, so a re-read fragment starts from it."""
        scope = self.notification_scope(read)
        keys = ((reference.seq, reference.message_id) for reference in references)
        known = {key: self.notification_known[scope, key]
                 for key in keys if (scope, key) in self.notification_known}
        return next(CheckedNotifications.for_references(references, known), UncheckedNotifications())

    def shows_notifications(self, view: NotificationSubscriber) -> bool:
        """Whether `view` is showing a read."""
        return view in self.notification_views

    def stop_notifications(self, view: NotificationSubscriber) -> bool:
        """Whether `view` was showing a read."""
        shown = view in self.notification_views
        self.notification_views.pop(view, None)
        self.observation.discard_notification_view(view)
        self._request_interest()
        return shown

    def _request_interest(self) -> None:
        wanted = ObserveNotifications(frozenset(self.notification_views.values()))
        if wanted != self.notification_interest:
            observed = self.observation.observed()
            self.notification_interest = wanted
            observed.observe_notifications(wanted)

    @handles(NotificationsObserved)
    def notifications_observed(self, result: NotificationsObserved, observed: Observing) -> None:
        if result.request not in self.notification_views.values():
            return
        scope = self.notification_scope(result.request)
        self.notification_known.update(((scope, key), rows) for key, rows in result.outcomes.items())
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_observed(result.outcomes)

    @handles(NotificationsUnreadable)
    def notifications_unreadable(self, result: NotificationsUnreadable, observed: Observing) -> None:
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_failed(result.error)

    @handles(NotificationsReload)
    def notifications_reload(self, result: NotificationsReload, observed: Observing) -> None:
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_reload()

    def sidebar_request(self) -> ObserveSidebar:
        return ObserveSidebar(
            self.app.project_dir,
            self.app.sidebar_show_stopped,
            self.app.sidebar_show_archived,
        )

    def update_sidebar_interest(self) -> None:
        wanted = self.sidebar_request() if self.showing_sidebar() or self.reference_views or self.sidebar_waiters else None
        if wanted != self.sidebar_interest:
            observed = self.observation.observed()
            self.sidebar_interest = wanted
            observed.observe_sidebar(wanted)

    def update_team_interest(self) -> None:
        selection: TeamBoardSelection = NamedTeamBoards(frozenset())
        for page_selection in tuple(self.team_pages.values()):
            selection = selection.combined(page_selection)
        wanted = ObserveTeamHud(selection) if self.team_pages else StopTeamHud()
        if wanted != self.team_interest:
            self.team_interest = wanted
            self.observation.observed().observe_team(wanted)

    def show_team(self, page: object, shown: bool, selection: TeamBoardSelection) -> None:
        """A team page started or stopped showing the heartbeat's frames."""
        if shown:
            self.team_pages[page] = selection
        else:
            self.team_pages.pop(page, None)
        self.update_team_interest()

    async def follow_sidebar(self, view: SidebarSubscriber[Observing, FailedObservation]) -> None:
        """``view`` follows the current observation until it leaves: bound now, and by every
        later activation whether it is hidden or shown, so no view keeps a retired one."""
        self.sidebar_views.add(view)
        observed = await self.preparation.run_thread(self.observation.observed)
        observed.show_sidebar(view)

    def leave_sidebar(self, view: SidebarSubscriber[Observing, FailedObservation]) -> None:
        self.sidebar_views.discard(view)
        self.update_sidebar_interest()

    def showing_sidebar(self) -> tuple[SidebarSubscriber[Observing, FailedObservation], ...]:
        """The following views that show the sidebar's rows now."""
        return tuple(view for view in self.sidebar_views if view.shows_sidebar())

    def show_references(self, view: object, shown: bool):
        if shown:
            self.reference_views.add(view)
        else:
            self.reference_views.discard(view)
        self.update_sidebar_interest()

    def reference_context(self, root: str) -> ReferenceContext:
        return self.observation.references_for(root)

    async def current_sidebar(self) -> SidebarObservation:
        """Return the source's current answer, including a failed observation."""
        observed = await self.preparation.run_thread(self.observation.observed)
        sidebar = observed.sidebar
        request = self.sidebar_request()
        if self.sidebar_interest == request and self.sidebar_current == request:
            return sidebar.observation
        waiter = asyncio.get_running_loop().create_future()
        pending = request, waiter
        self.sidebar_waiters.append(pending)
        self.update_sidebar_interest()
        try:
            return await waiter
        finally:
            if pending in self.sidebar_waiters:
                self.sidebar_waiters.remove(pending)
                self.update_sidebar_interest()

    async def update_thread_interest(self) -> None:
        """Acquire the observer through preparation before sending current-root interest."""
        observed = await self.preparation.run_thread(self.observation.observed)
        observed.thread_interest(self)

    def start(self) -> None:
        """Open the selected service and check the route selection once a second."""
        self.timer = self.app.repeat_ui(ROUTE_CHECK_SECONDS, self.check_route)
        self.check_route()

    async def stop_route_check(self) -> None:
        """Join the route check in flight, so nothing opens under the connection after it."""
        if self.route_task is not None:
            self.route_task.cancel()
            await asyncio.gather(self.route_task, return_exceptions=True)
            self.route_task = None

    async def stop_observing(self) -> None:
        """End view updates before teardown; outstanding read replies still complete."""
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        await self.stop_route_check()
        self.events.close_threads()
        self.app.cancel_operations(ThreadInterestUpdate)
        self.observation = self.observation.stop_updates()

    async def close(self) -> None:
        """Retire the observation once the views it served have closed."""
        async with AsyncResourceRelease() as release:
            # Join remote read processes only after acquired observations and
            # their pending reads have retired. Joining never borrows the UI loop.
            release.push_async_callback(asyncio.to_thread, self.connection.close)
            try:
                with ResourceRelease() as observation:
                    observation.callback(lambda: self.observation.subscriptions.close())
                    await self.stop_observing()
            finally:
                self.observation = ClosedObservation(access=self)
                for task in tuple(self.retiring):
                    release.push_async_callback(join_retirement, task)

    async def _retire_previous_connection(
        self, pending: tuple[asyncio.Task[None], ...], previous: CoreConnection
    ) -> None:
        """Join the previous observation's retirement tasks, then close its connection."""
        try:
            for task in pending:
                await join_retirement(task)
        finally:
            await asyncio.to_thread(previous.close)

    async def switch_connection(self, connection: CoreConnection) -> None:
        """Observe ``connection``'s Core in place of the current one's, the way a changed
        route is observed: its current observation adopts the old one, which retires with
        its subscriptions, and every view subscribed to this access rebinds on the
        CoordinationObserved that follows. The old connection closes once that retirement
        has joined, as close() orders it, tracked in ``self.retiring`` so opening the new
        bus's saved tabs does not wait on the old bus's teardown."""
        await self.stop_route_check()
        previous, self.connection = self.connection, connection
        # Another bus is not the lost one: it opens now, not when the old one's retry is due.
        self.retry.recovered()
        await self.observe_route()
        pending = tuple(self.retiring)
        cleanup = asyncio.create_task(self._retire_previous_connection(pending, previous))
        self.retiring.add(cleanup)
        cleanup.add_done_callback(self.retiring.discard)

    async def route_changed(self) -> bool:
        previous = self.observation
        await self.preparation.run_thread(self.open_current)
        return not previous.is_current()

    def check_route(self) -> None:
        if self.route_task is None or self.route_task.done():
            self.route_task = asyncio.create_task(self.observe_route())

    def focus_returned(self) -> None:
        """The app regained focus without suspending: clear backoff if currently failed."""
        self.observation.focus_returned(self)

    def resume(self) -> None:
        """The app returned from suspension (e.g. Android background/Doze or network switch):
        clear backoff, supersede any stalled route check, recycle kept sockets and re-establish
        observation immediately."""
        self.retry.recovered()
        if self.route_task is not None and not self.route_task.done():
            self.route_task.cancel()
        self.route_task = asyncio.create_task(self.resume_route())

    async def resume_route(self) -> None:
        previous = self.observation
        await self.preparation.run_thread(self.reopen_current)
        if not previous.is_current():
            self.events.publish(CoordinationObserved(self.revision))

    async def observe_route(self) -> None:
        """A changed route selection opens (and observes) the newly selected service."""
        if await self.route_changed():
            self.events.publish(CoordinationObserved(self.revision))

    def write(self, selected: CapturedSource, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. No route lock: the
        # store refuses a write an install holds, inside its own write transaction.
        self.confirm(selected)
        return operation(*args, **kwargs)
