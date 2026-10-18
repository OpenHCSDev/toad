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
from dataclasses import dataclass, field
from functools import partial
from collections.abc import Callable
from contextlib import ExitStack
from typing import TYPE_CHECKING, Protocol, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.coordination_errors import StaleRevision
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.presentation import NoRevision, ReadState
from agent_comms.private_path import FileRevision
from agent_comms.route_selection import RouteChanged, RouteSelection, run_selected_write
from agent_comms.ui_model.observation import (
    ObserveNotifications, NotificationsObserved, NotificationsUnreadable, ReadNotifications,
    AwaitedRead, ObservationProcess, ObserveSidebar, ObserveThreads, ObserveViews, RevisionObserved,
    SidebarObserved, SidebarUnreadable, ViewsRetired,
    StopObserving, StopSidebar, ThreadsObserved,
)
from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation
from agent_comms.ui_model.status import OpenThreadStatus
from toad.core.events import CoreEventStream, CoordinationObserved, ExternalTranscriptChanged, OpenTabsChanged, LinkContextChanged, ObservedServiceChanged, Subscription, ThreadRowsChanged
from toad.core_event_carrier import ThreadCallbackSubscription
from toad.resource_release import ResourceRelease
from toad.preferences import SETTINGS
from agent_comms.display_references import PendingReferences, UnavailableReferences

if TYPE_CHECKING:
    from toad.widgets.message_notifications import HistoryNotifications
    from agent_comms.comms import Comms
    from toad.app import ToadApp

T = TypeVar("T")

class RouteObservation:
    stamp = None

    def changed(self, stamp):
        return True

    def references_for(self, observed, root):
        return observed.references_for(root)

    def report(self, app):
        pass


@dataclass(frozen=True)
class WaitingRoute(RouteObservation):
    pass


@dataclass(frozen=True)
class ObservedRoute(RouteObservation):
    stamp: tuple[FileRevision | None, ...] = field()

    def changed(self, stamp):
        return stamp[0] != self.stamp[0]


@dataclass(frozen=True)
class FailedRoute(RouteObservation):
    error: Exception

    def references_for(self, observed, root):
        return UnavailableReferences(root, str(self.error))

    def report(self, app):
        app.notify(str(self.error), title="Reference source unavailable", severity="error")


# The active route file selects which root is observed; the observation
# process watches one root's stores, so the selection is checked here.
ROUTE_CHECK_SECONDS = 1.0


@dataclass(frozen=True)
class ObservedCommsService:
    """One opened service, its observation process and the sidebar model every view renders."""

    selection: RouteSelection
    service: Comms
    sidebar: SidebarModel
    process: ObservationProcess = field(compare=False)


class Observation(Protocol):
    observed_service: Comms | None
    sidebar: SidebarModel | None

    def current(self, access: CoordinationAccess) -> Comms: ...
    def require(self, access: CoordinationAccess, selected: RouteSelection) -> Comms: ...
    def attach(self, access: CoordinationAccess, previous: Observation) -> None: ...
    def retire(self, access: CoordinationAccess) -> None: ...
    async def read(self, access: CoordinationAccess, request: AwaitedRead): ...
    def notifications(self, access: CoordinationAccess, wanted: ObserveNotifications) -> None: ...
    def views(self, access: CoordinationAccess, request: ObserveViews) -> None: ...
    def sidebar_interest(self, access: CoordinationAccess) -> None: ...
    def references_for(self, root): ...
    async def current_references(self, access: CoordinationAccess, root): ...
    def thread_interest(self, access: CoordinationAccess) -> None: ...
    def stop(self) -> None: ...


class NotObserving(Observation):
    observed_service = sidebar = None

    def current(self, access):
        return access.open_current()

    def require(self, access, selected):
        return access.open_selected(selected)

    def attach(self, access, previous):
        pass

    def retire(self, access):
        pass

    async def read(self, access, request):
        await access.preparation.run_thread(access.open_current)
        return await access.observation.read(access, request)

    def notifications(self, access, wanted):
        pass

    def views(self, access, request):
        pass

    def sidebar_interest(self, access):
        pass

    def references_for(self, root):
        return PendingReferences(root)

    async def current_references(self, access, root):
        return access.reference_context(root)

    def thread_interest(self, access):
        pass

    def stop(self):
        pass


@dataclass(frozen=True)
class Observing(Observation):
    service: ObservedCommsService
    loop: asyncio.AbstractEventLoop

    @property
    def observed_service(self):
        return self.service.service

    @property
    def sidebar(self):
        return self.service.sidebar

    def current(self, access):
        return self.service.service

    def require(self, access, selected):
        return self.service.service if self.service.selection == selected else access.open_selected(selected)

    def attach(self, access, previous):
        previous.retire(access)
        if self is not access.observation:
            self.retire(access)
            return
        self.loop.add_reader(self.service.process.fileno(), self.receive, access)
        waiters, access.sidebar_waiters = access.sidebar_waiters, []
        for _, waiter in waiters:
            if not waiter.done():
                waiter.set_exception(RouteChanged("Comms service changed before the sidebar was read"))
        access.sidebar_interest = access.sidebar_current = None
        access.thread_status.clear()
        access.views_interest = None
        access.notification_views.clear()
        access.notification_interest = ObserveNotifications(frozenset())
        self.sidebar_interest(access)
        self.thread_interest(access)
        access.app.session_navigation.declare_views()
        access.events.publish(ObservedServiceChanged())

    def retire(self, access):
        self.loop.remove_reader(self.service.process.fileno())
        self.service.process.abandon_reads(StaleRevision("The Comms service was replaced before the read was answered"))
        task = asyncio.ensure_future(asyncio.to_thread(self.service.process.close))
        access.retiring.add(task)
        task.add_done_callback(access.retiring.discard)

    def receive(self, access):
        if self is not access.observation:
            return
        try:
            for result in self.service.process.results():
                access.dispatch_sync(result, self.service)
        except Exception as error:
            self.loop.remove_reader(self.service.process.fileno())
            access.app._handle_exception(error)

    async def read(self, access, request):
        return await self.service.process.read(request)

    def notifications(self, access, wanted):
        if wanted != access.notification_interest:
            access.notification_interest = wanted
            self.service.process.request(wanted)

    def views(self, access, request):
        if request != access.views_interest:
            access.views_interest = request
            self.service.process.request(request)

    def sidebar_interest(self, access):
        wanted = access.sidebar_request() if access.sidebar_views or access.reference_views or access.sidebar_waiters else None
        if wanted != access.sidebar_interest:
            access.sidebar_interest = wanted
            self.service.process.request(wanted if wanted is not None else StopSidebar())

    def references_for(self, root):
        return self.service.sidebar.observation.references_for(root)

    async def current_references(self, access, root):
        try:
            await access.current_sidebar()
        except RouteChanged:
            pass
        return access.reference_context(root)

    def thread_interest(self, access):
        self.service.process.request(ObserveThreads(access.events.observed_threads(str(self.service.service.root))))

    def stop(self):
        process = self.service.process
        process.request(StopObserving())
        self.loop.remove_reader(process.fileno())
        self.loop.add_reader(process.fileno(), process.results)


class CoordinationAccess(MroDispatch):
    """A validated Core route owns cached access, observations and UI write checks."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        from toad.acp.transcript_reader import CoordinationTranscriptReader

        self.transcripts = CoordinationTranscriptReader(self)
        self.observation: Observation = NotObserving()
        self.events = CoreEventStream(self)
        self.revision: ReadState = NoRevision()
        self.route_observation: RouteObservation = WaitingRoute()
        self.route_task: asyncio.Task[None] | None = None
        self.timer = None
        self.cleanup = ExitStack()
        self.opening = threading.Lock()
        self.preparation = app.preparation
        self.retiring: set[asyncio.Task[None]] = set()
        # One status row per open thread, whichever service it was read from.
        self.thread_status = OpenThreadStatus(app.call_next)
        # Views showing the sidebar model now, and consumers waiting for current rows.
        self.sidebar_views: WeakSet[object] = WeakSet()
        self.reference_views: WeakSet[object] = WeakSet()
        self.sidebar_waiters: list[tuple[ObserveSidebar, asyncio.Future[SidebarObservation]]] = []
        self.sidebar_interest: ObserveSidebar | None = None
        self.sidebar_current: ObserveSidebar | None = None
        self.views_interest: ObserveViews | None = None
        self.notification_views: WeakKeyDictionary[HistoryNotifications, ReadNotifications] = WeakKeyDictionary()
        self.notification_interest = ObserveNotifications(frozenset())

    @property
    def observed_service(self) -> Comms | None:
        return self.observation.observed_service

    @property
    def sidebar(self) -> SidebarModel | None:
        return self.observation.sidebar

    @property
    def service(self) -> Comms:
        """The observed service, opened on first use.

        Reading it is cheap: a changed route is the route check's to detect
        (``check_route``), so views do not capture the route (file reads
        under a lock) whenever they need the service.
        """
        return self.observation.current(self)

    def open_current(self) -> Comms:
        """Capture the current route and open (or keep) its service; file I/O."""
        return self.require(RouteSelection.capture())

    def require(self, selected: RouteSelection) -> Comms:
        """The service for ``selected``; a new selection opens it and starts its observation."""
        if RouteSelection.capture() != selected:
            raise RouteChanged("Comms route changed before the operation")
        with self.opening:
            return self.observation.require(self, selected)

    def open_selected(self, selected: RouteSelection) -> Comms:
        from agent_comms.comms import wire

        previous = self.observation
        with ExitStack() as acquisition:
            acquisition.enter_context(selected.route.hold_client_route())
            service = wire(selected.route)
            if service.root.resolve() != selected.root or RouteSelection.capture() != selected:
                raise RouteChanged("Comms route changed while opening the service")
            self.cleanup.enter_context(acquisition.pop_all())
        observed = Observing(ObservedCommsService(
            selected, service, SidebarModel(self.app.call_next), ObservationProcess(service.route)),
            self.app.running_loop)
        self.observation = observed
        self.revision = NoRevision()
        self.route_observation = WaitingRoute()
        observed.loop.call_soon_threadsafe(observed.attach, self, previous)
        return service

    async def read(self, request: AwaitedRead):
        return await self.observation.read(self, request)

    @handles(RevisionObserved)
    def revision_observed(self, result: RevisionObserved, observed: ObservedCommsService) -> None:
        previous = self.revision
        self.revision = result.revision
        if previous.status_changed_since(result.revision):
            self.events.publish(CoordinationObserved(result.revision))
        if previous.external_transcripts_changed_since(result.revision):
            self.events.publish(ExternalTranscriptChanged())

    @handles(SidebarObserved)
    def sidebar_observed(self, result: SidebarObserved, observed: ObservedCommsService) -> None:
        if result.request != self.sidebar_interest:
            return  # Read for an interest the views have since changed.
        app = self.app
        notice = observed.sidebar.observation.read_marker_notice()
        tabs = app.open_tabs
        previous_references = self.reference_context(str(observed.service.root))
        observed.sidebar.apply(result.snapshot, result.derived)
        if previous_references != self.reference_context(str(observed.service.root)):
            self.events.publish(LinkContextChanged())
        self.sidebar_current = result.request
        if result.snapshot.read_marker_notice and result.snapshot.read_marker_notice != notice:
            app.notify(result.snapshot.read_marker_notice, title="Read positions", severity="warning")
        if app.open_tabs != tabs:
            app.events.publish(OpenTabsChanged())
        for waiter in self.take_sidebar_waiters(result.request):
            waiter.set_result(observed.sidebar.observation)

    @handles(SidebarUnreadable)
    def sidebar_unreadable(self, result: SidebarUnreadable, observed: ObservedCommsService) -> None:
        if result.request != self.sidebar_interest:
            return
        observed.sidebar.clear(result.error)
        self.events.publish(LinkContextChanged())
        self.sidebar_current = result.request
        for waiter in self.take_sidebar_waiters(result.request):
            waiter.set_result(observed.sidebar.observation)
        self.app.notify(str(result.error), title="Sidebar unavailable", severity="error")

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
    def threads_observed(self, result: ThreadsObserved, observed: ObservedCommsService) -> None:
        self.thread_status.observed(result)
        self.events.publish(ThreadRowsChanged(str(observed.service.root), result.changed))

    @handles(ViewsRetired)
    def views_retired(self, result: ViewsRetired, observed: ObservedCommsService) -> None:
        self.app.session_navigation.views_retired(observed.service.root, result.retired)

    def show_notifications(self, view: HistoryNotifications, read: ReadNotifications | None) -> None:
        """Observe only original messages the views currently show."""
        if read is not None:
            self.notification_views[view] = read
        else:
            self.notification_views.pop(view, None)
        self.observation.notifications(self, ObserveNotifications(frozenset(self.notification_views.values())))

    @handles(NotificationsObserved)
    def notifications_observed(self, result: NotificationsObserved, observed: ObservedCommsService) -> None:
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_observed(result.outcomes)

    @handles(NotificationsUnreadable)
    def notifications_unreadable(self, result: NotificationsUnreadable, observed: ObservedCommsService) -> None:
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_failed(result.error)

    def show_views(self, threads: frozenset, channels: frozenset[str]) -> None:
        """The thread incarnations and channel views open on the observed root."""
        self.observation.views(self, ObserveViews(threads, channels))

    def sidebar_request(self) -> ObserveSidebar:
        state = self.app.saved_settings.state
        return ObserveSidebar(
            str(self.app.project_dir),
            SETTINGS.sidebar.show_stopped.bind(state).value,
            SETTINGS.sidebar.show_archived.bind(state).value,
        )

    def update_sidebar_interest(self) -> None:
        self.observation.sidebar_interest(self)

    def observe_thread_changes(self, view, scope: tuple[str, str], resume) -> ResourceRelease:
        """Hold the shared model while this native read waits for its own thread."""
        release = ResourceRelease()

        release.callback(view.retire_core, view.observe_core_callback(
            self.events, ThreadRowsChanged, resume,
            factory=partial(ThreadCallbackSubscription, scope=scope)))
        return release

    def show_sidebar(self, view: object, shown: bool) -> None:
        """A view started or stopped showing the sidebar model."""
        if shown:
            self.sidebar_views.add(view)
        else:
            self.sidebar_views.discard(view)
        self.update_sidebar_interest()

    def show_references(self, view, shown):
        if shown:
            self.reference_views.add(view)
        else:
            self.reference_views.discard(view)
        self.update_sidebar_interest()

    def reference_context(self, root):
        return self.route_observation.references_for(self.observation, root)

    async def current_references(self, root):
        return await self.observation.current_references(self, root)

    async def current_sidebar(self) -> SidebarObservation:
        """Return the source's current answer, including a failed observation."""
        request = self.sidebar_request()
        if self.sidebar_interest == request and self.sidebar_current == request:
            return self.observation.sidebar.observation
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
        await self.preparation.run_thread(self.open_current)
        self.observation.thread_interest(self)

    def start(self) -> None:
        """Open the selected service and check the route selection once a second."""
        self.observation.attach(self, NotObserving())
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
        self.observation.stop()

    async def close(self) -> None:
        await self.stop_observing()
        self.observation.retire(self)
        self.observation = NotObserving()
        await asyncio.gather(*self.retiring, return_exceptions=True)
        self.cleanup.close()

    def current_route_stamp(self) -> tuple[FileRevision | None, ...]:
        from agent_comms.active_route import active_route_path

        service = self.observed_service
        return (FileRevision.capture(active_route_path()),
                FileRevision.capture(service.root / "bus_meta.json") if service else None)

    async def route_changed(self) -> bool:
        stamp = await self.preparation.run_thread(self.current_route_stamp)
        return self.route_observation.changed(stamp)

    def check_route(self) -> None:
        if self.route_task is None or self.route_task.done():
            self.route_task = asyncio.create_task(self.observe_route())

    async def observe_route(self) -> None:
        """A changed route selection opens (and observes) the newly selected service."""
        root = str(self.observed_service.root) if self.observed_service is not None else ""
        previous_references = self.reference_context(root)
        try:
            stamp = await self.preparation.run_thread(self.current_route_stamp)
            if stamp == self.route_observation.stamp:
                return
            await self.preparation.run_thread(self.open_current)
            stamp = await self.preparation.run_thread(self.current_route_stamp)
        except (OSError, ValueError, RuntimeError) as error:
            self.route_observation = FailedRoute(error)
        else:
            self.route_observation = ObservedRoute(stamp)
        if previous_references != self.reference_context(root):
            self.events.publish(LinkContextChanged())
            if self.reference_views:
                self.route_observation.report(self.app)
        self.events.publish(CoordinationObserved(self.revision))

    def write(self, selected: RouteSelection, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. The existing
        # core route lock is held through the operation; no second lock/store.
        return run_selected_write(selected.root, operation, *args, implicit=selected.implicit, **kwargs)

