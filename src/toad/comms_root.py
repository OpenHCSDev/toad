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
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.message_reference import MessageReference
from agent_comms.child_process import join_retirement
from agent_comms.comms import Comms
from agent_comms.core_access import CoreAccess, LocalCoreAccess
from agent_comms.registry_document import RegistrySnapshot
from agent_comms.remote_core import RemoteCoreAccess
from agent_comms.tools import CommsRegistryTool
from agent_comms.display_references import PendingReferences, UnavailableReferences
from agent_comms.errors import RouteChangedError
from agent_comms.launch_root import LaunchRoot
from agent_comms.launch_runtime import LaunchRuntime
from metaclass_registry.mro_dispatch import MroDispatch, handles
from agent_comms.presentation import MessageNotification, NoRevision, ReadState
from agent_comms.revision_views import ExternalTranscriptsView, StatusView
from agent_comms.route_selection import RouteSelection
from agent_comms.root_runtime import RootRuntime
from agent_comms.ui_model.observation import (
    AwaitedRead,
    TeamHudObserved,
    TeamHudUnreadable,
    ObserveTeamHud,
    StopTeamHud,
    NotificationsObserved,
    NotificationsUnreadable,
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

if TYPE_CHECKING:
    from agent_comms.display_order import DisplayOrder
    from agent_comms.display_references import ReferenceContext
    from agent_comms.thread_identity import ThreadIncarnation

    from toad.app import ToadApp
    from toad.screens.team import TeamPage
    from toad.session_entry import SessionEntry
    from toad.session_navigation import SessionNavigation
    from toad.widgets.linked_rows import ReferenceRendering
    from toad.widgets.message_notifications import HistoryNotifications
    from toad.widgets.sidebar_tree import SidebarModelView

T = TypeVar("T")

ROUTE_CHECK_SECONDS = 1.0


class CoreConnection(ABC):
    """The selected Core transport: it owns its route selection and opens its observation."""

    @staticmethod
    def startup(arguments: list[str], published: Callable[[], LaunchRoot]) -> CoreConnection:
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

    @abstractmethod
    def route_selection(self) -> RouteSelection: ...

    @abstractmethod
    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """This connection's current observation, or the error that refuses it."""


class LocalCoreConnection(LaunchRoot, CoreConnection):
    """A local connection inherits the selected root and its launch behavior."""

    @classmethod
    def from_launch(cls, root: LaunchRoot) -> LocalCoreConnection:
        return cls(root.path)

    @property
    def location(self) -> str:
        return str(self.path)

    def route_selection(self) -> RouteSelection:
        return RouteSelection.of(self)

    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """Capture the current route and open its service, or expose the opening error."""
        selected: RouteSelection | UnselectedRoute = UnselectedRoute()
        try:
            selected = self.route_selection()
            return access.require(selected)
        except (OSError, ValueError, RuntimeError) as error:
            return access.observation.failed(error, selected)


class RemoteObservationNotServed(RuntimeError):
    """The connector answers this UI's Core requests but does not yet carry its observation."""


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
        raise RemoteObservationNotServed(
            f"{self.endpoint.url} answers Core requests; local route selection does not apply")

    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        return access.observation.adopt(ConnectorObservation(
            RemoteObservationNotServed(
                f"{self.endpoint.url} does not yet carry the sidebar, status and notification "
                "observation; conversation pages are read through its Core requests"),
            UnselectedRoute(), connection=self, access=access))


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

    def queue_service(self) -> Comms:
        raise RouteChangedError("The queue's original Comms source is unavailable")

    @abstractmethod
    async def read(self, request: AwaitedRead) -> object: ...

    def is_current(self) -> bool:
        return self is self.access.observation

    def observes(self, root: str | Path) -> bool:
        return False

    def uses(self, service: Comms) -> bool:
        return False

    def tab(self, entry: SessionEntry, sessions: SessionNavigation):
        return entry.unobserved_tab()

    def tabs(self, sessions: SessionNavigation):
        return {entry.identity: self.tab(entry, sessions) for entry in sessions.members}
    def require(self, access: CoordinationAccess, selected: RouteSelection):
        return access.open_selected(selected)
    def references_for(self, root: str) -> ReferenceContext:
        return PendingReferences(root)
    async def current_references(self, access: CoordinationAccess, root: str):
        return access.reference_context(root)

    def failed(self, error: Exception, selected):
        return self.adopt(FailedObservation(error, selected, access=self.access))

    def adopt[O: Observation](self, observation: O) -> O | Observation:
        """Make ``observation`` current unless it equals this one."""
        if observation == self:
            return self
        self.access.observation = observation
        self.access.app.running_loop.call_soon_threadsafe(observation.attach, self.access, self)
        return observation

    def stop_updates(self) -> Observation:
        self.updates.close()
        return self

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
    def service(self):
        raise self.error

    @property
    def core(self) -> CoreAccess:
        raise self.error

    @property
    def sidebar(self):
        raise self.error

    async def write_order(self, access: CoordinationAccess, root, channel, order: type[DisplayOrder]):
        raise self.error

    def references_for(self, root: str) -> ReferenceContext:
        return UnavailableReferences(root, str(self.error))

    def show_sidebar(self, view: SidebarModelView):
        view.bind_failed_observation(self)

    def activate(self, access: CoordinationAccess):
        self.observe_sidebar(None)

    def observe_sidebar(self, wanted):
        access = self.access
        for view in tuple(access.sidebar_views):
            self.show_sidebar(view)

    def observe_notifications(self, wanted: ObserveNotifications):
        for view in tuple(self.access.notification_views):
            view.notifications_failed(self.error)

    def thread_interest(self, access: CoordinationAccess):
        access.app.show_error(self.error, "Thread status unavailable")

    def observe_team(self, wanted: ObserveTeamHud | StopTeamHud):
        self.access.events.publish(TeamHudFailed(self.error))


@dataclass(frozen=True, eq=False)
class ConnectorObservation(FailedObservation):
    """Core answers this UI's requests through the connector. Every observed surface
    refuses with the declared error until the connector carries the observation."""

    connection: RemoteCoreConnection = field(kw_only=True, compare=False)

    @property
    def core(self) -> CoreAccess:
        return self.connection


@dataclass(frozen=True)
class Observing(Observation):
    """An observation answering through its process; where its Core is belongs to the member."""

    sidebar: SidebarModel
    process: ObservationProcess = field(compare=False)
    answering: ClassVar[type[AnsweringReads]]

    def queue_service(self) -> Comms:
        if not self.is_current():
            raise RouteChangedError("The queue's original Comms source retired")
        return self.service

    async def read(self, request: AwaitedRead) -> object:
        return await self.process.read(request)

    @property
    @abstractmethod
    def root(self) -> Path:
        """The bus root this observation's Core serves; root-keyed requests and views key on it."""

    def observes(self, root: str | Path) -> bool:
        return Path(root).expanduser().resolve() == self.root

    def registry(self) -> RegistrySnapshot:
        """Core's thread registry: names, renames and recorded threads resolve against it."""
        return self.core.call(CommsRegistryTool()).snapshot

    def tab(self, entry: SessionEntry, sessions: SessionNavigation):
        return entry.tab(sessions, self)

    def show_sidebar(self, view: SidebarModelView) -> None:
        if self.is_current():
            view.bind_observation(self)

    def uses(self, service: Comms) -> bool:
        return False

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
        super().stop_updates()
        self.process.request(StopObserving())
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
        try:
            await access.current_sidebar()
        except RouteChangedError:
            return await access.observation.current_references(access, root)
        return access.reference_context(root)

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

    def opened_selection(self) -> RouteSelection:
        return self.selection

    def uses(self, service: Comms) -> bool:
        return self.service is service

    @property
    def core(self) -> CoreAccess:
        return LocalCoreAccess(self.service)

    async def write_order(self, access: CoordinationAccess, root, channel, order: type[DisplayOrder]):
        if root is not None and not self.observes(root):
            raise ValueError("Comms route changed before sorting")
        return await access.preparation.run_thread(
            access.write, self.selection, order.store_channel_order, self.service.channels, channel)

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

    def selected(self, source: str | Path) -> RouteSelection:
        """Select this app's route and refuse a foreign source."""
        return self.selection.require_source(source)

    def current(self, source: str | Path) -> bool:
        """Whether a source still belongs to this app's current route."""
        return self.selection.root_is_current(source)

    def open_current(self) -> Observing | FailedObservation:
        """The connection's current observation, or the error that refuses it."""
        with self.opening:
            return self.connection.open_current(self)

    def confirm(self, selected: RouteSelection) -> None:
        if self.selection != selected:
            raise RouteChangedError("Comms route changed before the operation")

    def require(self, selected: RouteSelection) -> Observing:
        """The service for ``selected``; a new selection opens it and starts its observation."""
        self.confirm(selected)
        with self.opening:
            return self.observation.require(self, selected)

    def open_selected(self, selected: RouteSelection) -> Observing:
        def attach() -> Observing:
            previous = self.observation
            service = Comms(selected.route)
            if service.root.resolve() != selected.root:
                raise RouteChangedError("Comms route changed while opening the service")
            self.confirm(selected)
            return self.adopt(previous, LocalObserving(
                SidebarModel(self.app.call_next), ObservationProcess(service.route),
                selection=selected, service=service, access=self))

        return RootRuntime.attachment(selected.root, LaunchRuntime.running()).proceed(
            attach, self.app.succeed_onto,
        )

    def adopt[O: Observing](self, previous: Observation, observed: O) -> O:
        """Make a newly opened observation current; it retires with its subscriptions."""
        observed.subscriptions.callback(observed.retire, self)
        self.observation = observed
        self.app.running_loop.call_soon_threadsafe(observed.attach, self, previous)
        return observed

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

    def show_notifications(self, view: HistoryNotifications, read: ReadNotifications) -> None:
        self.notification_views[view] = read
        if known := self.known_outcomes(read):
            view.notifications_observed(known)
        self._request_interest()

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

    def stop_notifications(self, view: HistoryNotifications) -> None:
        self.notification_views.pop(view, None)
        self._request_interest()

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
        self.app.workers.cancel_group(self.app, "thread-interest")
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

    def write(self, selected: RouteSelection, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. No route lock: the
        # store refuses a write an install holds, inside its own write transaction.
        self.confirm(selected)
        return operation(*args, **kwargs)
