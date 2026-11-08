"""Toad's cached access to the Comms service of the current route.

Core owns route selection and guarded writes (``agent_comms.route_selection``)
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
from concurrent.futures import Future
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.message_reference import MessageReference
from agent_comms.child_process import HelperStart, SpawnedHelper, join_retirement
from agent_comms.comms import Comms
from agent_comms.active_route import CommsRoute
from agent_comms.core_access import LocalCoreAccess
from agent_comms.transport.request import CoreAccess
from agent_comms.registry.registry_document import ProjectThreadSelection, RegistrySnapshot
from toad.db import UNSCOPED_TABS, TabScope
from toad.referenced_core import ReferencedCore
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.threads import Thread
from agent_comms.connector_store import HeldUiProfiles, OpenableProfile
from agent_comms.tailnet_buses import PeerHoldsBus, TailnetBuses
from agent_comms.remote_core import RemoteCoreAccess
from agent_comms.channel_targets import NamedTarget
from toad.widgets.thread_comms_source import RelationshipReads
from toad.core.context_reads import ContextReads
from agent_comms.historical_views import HistoricalSenders, HistoricalThread
from agent_comms.transport.tools.sidebar import (
    CommsRegistryTool,
    CommsHistoricalThreadsTool,
    CommsMarkThreadViewReadTool, CommsServedRootTool, CommsSessionThreadTool,
    CommsUserSendTool,
)
from agent_comms.transcripts import TranscriptCursor
from agent_comms.display_references import PendingReferences, RegistryReferenceSource, UnavailableReferences
from agent_comms.errors import RouteChangedError
from agent_comms.launch_root import LaunchRoot
from agent_comms.launch_runtime import LaunchRuntime
from metaclass_registry.mro_dispatch import MroDispatch, handles
from agent_comms.message_notification import MessageNotification
from agent_comms.presentation import NoRevision, ReadState
from agent_comms.revision_views import ExternalTranscriptsView, RegistrationsView, StatusView
from agent_comms.route_selection import RouteSelection
from agent_comms.root_runtime import RootRuntime
from agent_comms.ui_model.observation import (
    AwaitedRead,
    TeamHudObserved,
    TeamHudUnreadable,
    ObserveTeamHud,
    StopTeamHud,
    NotificationsObserved,
    NotificationsReload,
    NotificationsUnreadable,
    LocalRouteObservation,
    ObservationSource,
    ObservationProcess,
    Observed,
    ObserveNotifications,
    ObserveSidebar,
    ObserveThreads,
    ObserveViews,
    ReadNotifications,
    RevisionObserved,
    SidebarObserved,
    SidebarPreparing,
    SidebarUnreadable,
    StopObserving,
    StopSidebar,
    ThreadsObserved,
    ViewsRetired,
)
from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation
from agent_comms.ui_model.status import OpenThreadStatus

from toad.core.events import (
    ThreadInterestUpdate,
    TeamHudChanged,
    TeamHudFailed,
    CoordinationObserved,
    CoreEventStream,
    ExternalTranscriptChanged,
    LinkContextChanged,
    ObservedServiceChanged,
    OpenTabsChanged,
    SidebarPresented,
    ThreadRowsChanged,
)
from toad.core_event_carrier import CoreEventReceiver, ThreadCallbackSubscription
from toad.notification_status import CheckedNotifications, NotificationStatus, UncheckedNotifications
from toad.resource_release import AsyncResourceRelease, ResourceRelease
from agent_comms.transport.request import ToolRequest

if TYPE_CHECKING:
    from agent_comms.display_references import ReferenceContext
    from agent_comms.registry.thread_identity import ThreadIncarnation

    from toad.app import ToadApp
    from toad.screens.team import TeamPage
    from toad.session_entry import SessionEntry
    from toad.session_navigation import SessionNavigation
    from toad.widgets.linked_rows import ReferenceRendering
    from toad.widgets.message_notifications import HistoryNotifications
    from toad.widgets.sidebar_tree import SidebarModelView

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

    helper_start: ClassVar[HelperStart] = SpawnedHelper()
    """How this launch starts its local route observer and its render workers."""

    @staticmethod
    def select(arguments: list[str], published: Callable[[], LaunchRoot]) -> CoreConnection:
        """Select once at the process boundary; a UI profile selects the remote Core."""
        if RemoteCoreConnection.argument in arguments:
            return RemoteCoreConnection.startup(arguments)
        return LocalCoreConnection.from_launch(LaunchRoot.startup(arguments, published))

    def open_access(self, app: ToadApp) -> CoordinationAccess:
        return CoordinationAccess(app, self)

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
    def observation_source(self, route: CommsRoute) -> ObservationSource:
        """What serves this connection's observation of ``route``."""

    @abstractmethod
    def capture(self, access: CoordinationAccess, source: str | Path) -> CapturedSource:
        """The source a UI action reads under, refused when it is not this Core's."""

    @abstractmethod
    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """This connection's current observation, or the error that refuses it."""

    @abstractmethod
    def holds(self, access: CoordinationAccess, source: str | Path) -> bool:
        """Whether ``source`` still belongs to what this connection currently observes."""

    @abstractmethod
    def observing(self, access: CoordinationAccess, source: str | Path) -> Observing:
        """The observation serving ``source``, or the refusal that it is not this Core's."""


class LocalCoreConnection(LaunchRoot, CoreConnection):
    """A local connection inherits the selected root and its launch behavior."""

    @classmethod
    def from_launch(cls, root: LaunchRoot) -> LocalCoreConnection:
        return cls(root.path)

    @property
    def location(self) -> str:
        return str(self.path)

    def tab_scopes(self) -> tuple[TabScope, ...]:
        """Tabs saved before scopes existed were local sessions' tabs; this Core reads them as
        its own and rewrites them under its location."""
        return (*super().tab_scopes(), UNSCOPED_TABS)

    def route_selection(self) -> RouteSelection:
        return RouteSelection.of(self)

    def observation_source(self, route: CommsRoute) -> ObservationSource:
        """A local route is observed in a process this machine starts for it."""
        return LocalRouteObservation(route, self.helper_start)

    def capture(self, access: CoordinationAccess, source: str | Path) -> SelectedRoute:
        return SelectedRoute(self.route_selection().require_source(source))

    def holds(self, access: CoordinationAccess, source: str | Path) -> bool:
        """The held launch route's root."""
        return self.route_selection().root_is_current(source)

    def observing(self, access: CoordinationAccess, source: str | Path) -> Observing:
        """Select this app's route for ``source`` and open its observation."""
        return access.require(self.route_selection().require_source(source))

    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """Capture the current route and open its service, or expose the opening error."""
        selected: RouteSelection | UnselectedRoute = UnselectedRoute()
        try:
            selected = self.route_selection()
            return access.require(selected)
        except (OSError, ValueError, RuntimeError) as error:
            return access.observation.failed(error, selected)


class RemoteUserMissing(RuntimeError):
    """The remote Core holds no user thread; only a UI on Core's own machine claims one."""


class RemoteRouteNotSelectable(RuntimeError):
    """A remote Core is observed through the connector; it has no local route to select."""


@dataclass(frozen=True)
class RemoteCoreConnection(RemoteCoreAccess, CoreConnection):
    """The owner's UI profile is the remote connection: Core answers through the connector."""

    argument: ClassVar[str] = "--comms-profile"

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

    def route_selection(self) -> RouteSelection:
        raise RemoteRouteNotSelectable(
            f"{self.endpoint.url} answers Core requests; local route selection does not apply")

    def observation_source(self, route: CommsRoute) -> ObservationSource:
        """The connector serves this UI's observation; it is the source."""
        return self

    def capture(self, access: CoordinationAccess, source: str | Path) -> CurrentObservation:
        return CurrentObservation(self.observing(access, source))

    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """The current observation through this connector; the observation decides whether
        it already is one."""
        return access.observation.through(self, access)

    def holds(self, access: CoordinationAccess, source: str | Path) -> bool:
        """The root the connector's Core serves, as the current observation holds it."""
        return access.observation.observed().observes(source)

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


class PickerRow(ABC):
    """One row the bus picker shows, and what picking it does.

    A bus this Toad can open and a peer it has only discovered are both rows, and they do
    different things when picked. Each says which, so the picker calls the row rather than
    asking what kind it is.
    """

    @abstractmethod
    def label(self) -> str:
        """How the picker names this row in one line."""

    @abstractmethod
    def chosen(self, app) -> None:
        """What picking this row does."""

    def same_bus(self, found: PeerHoldsBus) -> bool:
        """Whether this row is already that machine's bus, so the picker shows one row for
        it. Most rows are not any machine the tailnet reports; the ones that are say so."""
        return False

    def removable(self) -> bool:
        """Whether a reader can take this row off the list. Nothing is, by default: this
        machine's own bus and a machine the tailnet reports are facts, not saved entries."""
        return False

    def remove(self) -> None:
        """Take this row off the list for good. Only a row that says it is removable."""
        raise TypeError(f"{type(self).__name__} is not a saved row")


class BusChoice(PickerRow):
    """A bus the next launch of this Toad selects.

    `CoreConnection.select` chooses once at the process boundary and tab scopes are
    written under that connection's location, so a reader changing bus relaunches onto
    their choice rather than re-parenting every observation in place. The choice owns
    how it writes itself into the next launch's arguments; nothing else spells them.
    """

    def chosen(self, app) -> None:
        """A bus is opened by ending this session onto it."""
        app.open_bus(self)

    @abstractmethod
    def arguments(self, argv: Sequence[str]) -> tuple[str, ...]:
        """``argv`` rewritten so the next launch opens this bus."""

    @staticmethod
    def without_profile(argv: Sequence[str]) -> tuple[str, ...]:
        """``argv`` with every profile selection removed, so one launch names one bus."""
        remaining = list(argv)
        while RemoteCoreConnection.argument in remaining:
            index = remaining.index(RemoteCoreConnection.argument)
            del remaining[index:index + 2]
        return tuple(remaining)

    @staticmethod
    def offered(now: float) -> tuple[BusChoice, ...]:
        """This machine's own bus, then every remote one it holds an open profile for."""
        return (LocalBus(), *(
            HeldBus(entry) for entry in HeldUiProfiles.held(now)
            if isinstance(entry, OpenableProfile)
        ))


@dataclass(frozen=True)
class LocalBus(BusChoice):
    """This machine's own bus, which a launch opens when it names no profile."""

    def label(self) -> str:
        return "This machine"

    def arguments(self, argv: Sequence[str]) -> tuple[str, ...]:
        return self.without_profile(argv)


@dataclass(frozen=True)
class HeldBus(BusChoice):
    """A remote bus this machine holds an unexpired profile for."""

    profile: OpenableProfile

    def label(self) -> str:
        return self.profile.label()

    def same_bus(self, found: PeerHoldsBus) -> bool:
        """The route this profile was held with names the address it was reached on, which
        is the address the tailnet reports for that machine."""
        return self.profile.profile.route.reaches(found.peer.address)

    def arguments(self, argv: Sequence[str]) -> tuple[str, ...]:
        return (*self.without_profile(argv),
                RemoteCoreConnection.argument, str(self.profile.path))

    def removable(self) -> bool:
        """A held profile is the saved entry, so this is the row that can be removed."""
        return True

    def remove(self) -> None:
        """Forget this bus: the profile file IS the saved entry, so deleting it is the
        removal. Tristan: type an address, save it, and be able to remove saved ones
        again - and HeldUiProfiles.held already lists exactly the files in that directory,
        so there is no second record of what is saved to keep in step."""
        self.profile.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class DiscoveredPeer(PickerRow):
    """A tailnet machine holding a bus this one has no profile for yet.

    Picking it asks that machine for one. It had to say "grant one over there and hold it
    here" while the hoop it described was a person carrying a file between two machines that
    can already talk.
    """

    found: PeerHoldsBus

    def label(self) -> str:
        return self.found.label()

    def chosen(self, app) -> None:
        """Ask it for a profile and open it: a bus on your own tailnet needs no errand.

        Tristan: "it's a bus on my private tailnet why would want to have to jupm throuhg
        hoops". The peer decides whether its endpoint is tailnet-only and says no itself
        when it is not (agent_comms.served_endpoints.ProfileOffer).
        """
        app.ask_peer_for_profile(self.found)


@dataclass(frozen=True)
class UnselectedRoute:
    """Route capture failed before a validated selection existed."""


@dataclass(frozen=True, kw_only=True)
class Observation(ABC):
    access: CoordinationAccess = field(compare=False)
    subscriptions: ResourceRelease = field(default_factory=ResourceRelease, compare=False)
    # View updates end before the views close; `subscriptions` retires the observation after them.
    updates: ResourceRelease = field(default_factory=ResourceRelease, compare=False)

    def observed(self):
        return self

    def queue_observing(self) -> Observing:
        raise RouteChangedError("The queue's original Core source is unavailable")

    @abstractmethod
    async def read(self, request: AwaitedRead) -> object: ...

    def is_current(self) -> bool:
        return self is self.access.observation

    def observes(self, root: str | Path) -> bool:
        return False

    def serving(self, source: str | Path):
        """This observation, when ``source`` is the root it observes."""
        if not self.observes(source):
            raise RouteChangedError(f"{source} is not the root this UI observes")
        return self

    def tab(self, entry: SessionEntry, sessions: SessionNavigation):
        return entry.unobserved_tab()

    def tabs(self, sessions: SessionNavigation):
        return {entry.identity: self.tab(entry, sessions) for entry in sessions.members}
    def require(self, access: CoordinationAccess, selected: RouteSelection):
        return access.open_selected(selected)

    def through(self, connection: RemoteCoreConnection, access: CoordinationAccess):
        """No observation through ``connection`` is current yet: open one."""
        return connection.observe(access)
    def references_for(self, root: str) -> ReferenceContext:
        return PendingReferences(root)
    async def current_references(self, access: CoordinationAccess, root: str):
        return access.reference_context(root)

    def failed(self, error: Exception, selected):
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

    def attach(self, access, previous):
        previous.subscriptions.close()
        if not self.is_current():
            self.subscriptions.close()
            return
        waiters, access.sidebar_waiters = access.sidebar_waiters, []
        for _, waiter in waiters:
            if not waiter.done():
                waiter.set_exception(RouteChangedError("Comms service changed before the sidebar was read"))
        access.revision = NoRevision()
        access.sidebar_interest = access.sidebar_current = None
        access.team_interest = StopTeamHud()
        access.thread_status.clear()
        access.views_interest = None
        access.notification_views.clear()
        access.notification_known.clear()
        access.notification_interest = ObserveNotifications(frozenset())
        self.activate(access)
        access.events.publish(ObservedServiceChanged())


class NotObserving(Observation):
    def observed(self):
        return self.access.open_current()

    async def read(self, request: AwaitedRead) -> object:
        return await self.observed().read(request)


@dataclass(frozen=True, eq=False)
class FailedObservation(Observation):
    error: Exception = field(compare=False, repr=False)
    selection: RouteSelection | UnselectedRoute

    async def read(self, request: AwaitedRead) -> object:
        raise self.error

    def __eq__(self, other: object) -> bool:
        # Exceptions declare their type, constructor fields and extra state through
        # reconstruction; OSError includes filenames that are absent from args.
        return (isinstance(other, FailedObservation)
                and self.selection == other.selection
                and self.error.__reduce__() == other.error.__reduce__())

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

    def show_sidebar(self, view: SidebarModelView):
        view.bind_failed_observation(self)

    def activate(self, access: CoordinationAccess):
        for view in tuple(access.sidebar_views):
            self.show_sidebar(view)

    def observe_sidebar(self, wanted):
        """Failure was published on activation; interest changes cannot rebind its views."""

    def observe_notifications(self, wanted: ObserveNotifications):
        for view in tuple(self.access.notification_views):
            view.notifications_failed(self.error)

    def thread_interest(self, access: CoordinationAccess):
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

    def send_user_message(self, target: NamedTarget, body: str) -> MessageReference:
        """The owner's input, published by Core under the owner's identity, in process or
        across the connector; the reference is what the view waits to draw."""
        return self.core.call(CommsUserSendTool(target=target.name, body=body)).message.source

    def mark_thread_read(self, identity, project: Path, through: TranscriptCursor) -> None:
        """Acknowledge, as the owner, what this UI displayed of one thread: Core applies it,
        in process or across the connector."""
        thread = identity.resolve_thread(self, project)
        self.core.call(CommsMarkThreadViewReadTool(thread=thread, through=through))

    def tab(self, entry: SessionEntry, sessions: SessionNavigation):
        return entry.tab(sessions, self)

    def show_sidebar(self, view: SidebarModelView) -> None:
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
            self.access.dispatch_sync(result, self)

    def receive_failed(self, error: Exception):
        if self.is_current():
            self.failed(error, self.opened_selection())
            self.access.app._handle_exception(error)

    def views_changed(self, event=None, subscription=None):
        access, root = self.access, str(self.root)
        threads: set[ThreadIncarnation] = set()
        channels: set[str] = set()
        for member in access.app.session_navigation.members:
            threads.update(identity for owner, identity in member.original_threads(access.app.session_navigation) if owner == root)
            channels.update(target for owner, target in member.original_channels() if owner == root)
        request = ObserveViews(frozenset(threads), frozenset(channels))
        if request != access.views_interest:
            access.views_interest = request
            self.process.request(request)

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
        self.process.request(ObserveThreads(access.events.observed_threads(str(self.root))))

    def observe_sidebar(self, wanted):
        self.process.request(wanted if wanted is not None else StopSidebar())

    def observe_notifications(self, wanted: ObserveNotifications):
        self.process.request(wanted)

    def observe_team(self, wanted: ObserveTeamHud | StopTeamHud):
        self.process.request(wanted)

class AnsweringReads(Observing):
    """Interests have ended; acquired reads keep their process and release owners. Each
    location's member declares the observation it answers for once interests stop."""

    def __init_subclass__(cls, *, answers_for: type[Observing], **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        answers_for.answering = cls

    def stop_updates(self) -> AnsweringReads:
        return self

    def views_changed(self, event=None, subscription=None):
        pass

    def thread_interest(self, access: CoordinationAccess):
        pass

    def observe_sidebar(self, wanted):
        pass

    def observe_notifications(self, wanted: ObserveNotifications):
        pass

    def observe_team(self, wanted: ObserveTeamHud | StopTeamHud):
        pass


@dataclass(frozen=True)
class LocalObserving(Observing):
    """Core in this process, opened for one validated route selection."""

    selection: RouteSelection = field(kw_only=True)
    service: Comms = field(kw_only=True)

    @property
    def root(self) -> Path:
        return self.selection.root

    def observes(self, root: str | Path) -> bool:
        return Path(root).expanduser().resolve() == self.root

    def opened_selection(self) -> RouteSelection:
        return self.selection

    def user_identity(self, project: Checkout) -> Thread:
        """In process, the user thread is read, or claimed for this project's checkout."""
        return self.service.messaging.user_identity(project)

    @property
    def core(self) -> CoreAccess:
        return LocalCoreAccess(self.service)

    def require(self, access: CoordinationAccess, selected: RouteSelection):
        return self if self.selection == selected else access.open_selected(selected)


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

    def user_identity(self, project: Checkout) -> Thread:
        """Across the connector the user thread is Core's; this machine's checkout claims nothing."""
        return self.registry().user_thread().require(RemoteUserMissing(
            f"{self.connection.location} has no user thread; open a UI on Core's machine first"))

    def opened_selection(self) -> UnselectedRoute:
        return UnselectedRoute()

    @property
    def core(self) -> CoreAccess:
        return self.connection


@dataclass(frozen=True)
class LocalAnsweringReads(AnsweringReads, LocalObserving, answers_for=LocalObserving):
    pass


@dataclass(frozen=True)
class RemoteAnsweringReads(AnsweringReads, RemoteObserving, answers_for=RemoteObserving):
    pass


class CoordinationAccess(MroDispatch):
    """A validated Core route owns cached access, observations and UI write checks."""

    def __init__(self, app: ToadApp, connection: CoreConnection) -> None:
        self.app = app
        self.connection = connection
        from toad.acp.transcript_reader import CoordinationTranscriptReader

        self.transcripts = CoordinationTranscriptReader(self)
        self.observation: Observation = NotObserving(access=self)
        self.events = CoreEventStream(self)
        self.revision: ReadState = NoRevision()
        self.route_task: asyncio.Task[None] | None = None
        self.timer = None
        self.opening = threading.RLock()
        self.preparation = app.preparation
        self.retiring: set[asyncio.Task[None]] = set()
        # One status row per open thread, whichever service it was read from.
        self.thread_status = OpenThreadStatus(app.call_next)
        # Views showing the sidebar model now, and consumers waiting for current rows.
        self.sidebar_views: WeakSet[SidebarModelView] = WeakSet()
        self.reference_views: WeakSet[object] = WeakSet()
        self.sidebar_waiters: list[tuple[ObserveSidebar, asyncio.Future[SidebarObservation]]] = []
        self.sidebar_interest: ObserveSidebar | None = None
        self.sidebar_current: ObserveSidebar | None = None
        self.views_interest: ObserveViews | None = None
        self.notification_views: WeakKeyDictionary[HistoryNotifications, ReadNotifications] = WeakKeyDictionary()
        # The last answer for each message under each read scope (root, display, source).
        # A scroll changes which messages a view reads, never what is already known.
        self.notification_known: dict[tuple[ReadNotifications, tuple[int, str]], tuple[MessageNotification, ...]] = {}
        self.notification_interest = ObserveNotifications(frozenset())
        # Open team pages; the heartbeat's frames are observed only while one is shown.
        self.team_pages: WeakSet[TeamPage] = WeakSet()
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

    def open_selected(self, selected: RouteSelection) -> Observing:
        def attach() -> Observing:
            previous = self.observation
            service = Comms(selected.route)
            if service.root.resolve() != selected.root:
                raise RouteChangedError("Comms route changed while opening the service")
            self.confirm_route(selected)
            return previous.adopt(LocalObserving(
                SidebarModel(self.app.call_next), ObservationProcess(self.connection.observation_source(service.route)),
                selection=selected, service=service, access=self))

        return RootRuntime.attachment(selected.root, LaunchRuntime.running()).proceed(
            attach, self.app.succeed_onto,
        )

    def observe_remote(self, connection: RemoteCoreConnection, root: Path) -> RemoteObserving:
        """Observe the Core behind the connector: its peer carries the observation, and the
        root it serves keys every root-scoped request."""
        with self.opening:
            return self.observation.adopt(RemoteObserving(
                SidebarModel(self.app.call_next), ObservationProcess(connection),
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
        self.events.publish(TeamHudChanged(result.huds))

    @handles(TeamHudUnreadable)
    def team_hud_unreadable(self, result: TeamHudUnreadable, observed: Observing) -> None:
        self.events.publish(TeamHudFailed(result.error))

    @handles(SidebarObserved)
    def sidebar_observed(self, result: SidebarObserved, observed: Observing) -> None:
        if result.request != self.sidebar_interest:
            return  # Read for an interest the views have since changed.
        app = self.app
        notice = observed.sidebar.observation.read_marker_notice()
        modes = app.tab_order.names
        previous_references = self.reference_context(str(observed.root))
        observed.sidebar.apply(result.snapshot, result.derived)
        self.present_sidebar()
        if previous_references != self.reference_context(str(observed.root)):
            self.events.publish(LinkContextChanged())
        self.sidebar_current = result.request
        result.snapshot.read_marker_notice.notify_if_new(
            notice, lambda text: app.notify(text, title="Read positions", severity="warning"))
        if app.tab_order.names != modes:
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
        for view in tuple(self.sidebar_views):
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
        self.app.session_navigation.views_retired(observed.root, result.retired)

    def show_notifications(self, view: HistoryNotifications, read: ReadNotifications) -> bool:
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

    def stop_notifications(self, view: HistoryNotifications) -> bool:
        """Whether `view` was showing a read."""
        shown = view in self.notification_views
        self.notification_views.pop(view, None)
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
        sidebar = self.app.saved_settings.current.sidebar
        return ObserveSidebar(
            self.app.project_dir,
            sidebar.show_stopped,
            sidebar.show_archived,
        )

    def observe_thread_changes(
        self,
        view: CoreEventReceiver,
        scope: tuple[str, str],
        resume: Callable[[ThreadRowsChanged], None],
    ) -> ResourceRelease:
        """Hold the shared model while this native read waits for its own thread."""
        release = ResourceRelease()

        release.callback(view.retire_core, view.observe_core_callback(
            self.events, ThreadRowsChanged, resume,
            factory=partial(ThreadCallbackSubscription, scope=scope)))
        return release

    def update_sidebar_interest(self) -> None:
        wanted = self.sidebar_request() if self.sidebar_views or self.reference_views or self.sidebar_waiters else None
        if wanted != self.sidebar_interest:
            observed = self.observation.observed()
            self.sidebar_interest = wanted
            observed.observe_sidebar(wanted)

    def update_team_interest(self) -> None:
        wanted = ObserveTeamHud() if self.team_pages else StopTeamHud()
        if wanted != self.team_interest:
            self.team_interest = wanted
            self.observation.observed().observe_team(wanted)

    def show_team(self, page: TeamPage, shown: bool) -> None:
        """A team page started or stopped showing the heartbeat's frames."""
        if shown:
            self.team_pages.add(page)
        else:
            self.team_pages.discard(page)
        self.update_team_interest()

    def show_sidebar(self, view: SidebarModelView, shown: bool) -> None:
        """A view started or stopped showing the sidebar model."""
        if shown:
            self.sidebar_views.add(view)
        else:
            self.sidebar_views.discard(view)
        self.update_sidebar_interest()

    def show_references(self, view: ReferenceRendering, shown: bool):
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
        self.timer = self.app.set_interval(ROUTE_CHECK_SECONDS, self.check_route)
        self.check_route()

    async def stop_observing(self) -> None:
        """End view updates before teardown; outstanding read replies still complete."""
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.route_task is not None:
            self.route_task.cancel()
            await asyncio.gather(self.route_task, return_exceptions=True)
            self.route_task = None
        self.events.close_threads()
        ThreadInterestUpdate.cancel_all(self.app)
        self.observation = self.observation.stop_updates()

    async def close(self) -> None:
        """Retire the observation once the views it served have closed."""
        async with AsyncResourceRelease() as release:
            try:
                with ResourceRelease() as observation:
                    observation.callback(lambda: self.observation.subscriptions.close())
                    await self.stop_observing()
            finally:
                self.observation = NotObserving(access=self)
                for task in tuple(self.retiring):
                    release.push_async_callback(join_retirement, task)

    async def route_changed(self) -> bool:
        previous = self.observation
        await self.preparation.run_thread(self.open_current)
        return not previous.is_current()

    def check_route(self) -> None:
        if self.route_task is None or self.route_task.done():
            self.route_task = asyncio.create_task(self.observe_route())

    async def observe_route(self) -> None:
        """A changed route selection opens (and observes) the newly selected service."""
        if await self.route_changed():
            self.events.publish(CoordinationObserved(self.revision))

    def write(self, selected: CapturedSource, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. No route lock: the
        # store refuses a write an install holds, inside its own write transaction.
        self.confirm(selected)
        return operation(*args, **kwargs)
