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
from collections.abc import Callable
from contextlib import ExitStack
from typing import TYPE_CHECKING, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.coordination_errors import StaleRevision
from agent_comms.mro_dispatch import MroDispatch, handles
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
from toad.core.events import CoreEventStream, CoordinationObserved, ExternalTranscriptChanged, OpenTabsChanged, LinkContextChanged, ObservedServiceChanged, ThreadRowsChanged
from toad.resource_release import ResourceRelease
from toad.preferences import SETTINGS
from agent_comms.display_references import PendingReferences, UnavailableReferences

if TYPE_CHECKING:
    from toad.widgets.message_notifications import HistoryNotifications
    from agent_comms.comms import Comms
    from agent_comms.presentation import WireRevision
    from toad.app import ToadApp
    from toad.widgets.observed_thread_activity import ThreadStatusOwner

T = TypeVar("T")

class RouteObservation:
    stamp = None

    def changed(self, stamp):
        return True

    def references_for(self, observed, root):
        return observed.sidebar.references_for(root) if observed is not None else PendingReferences(root)

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
    events: CoreEventStream = field(compare=False)

    def __post_init__(self) -> None:
        self.sidebar.threads.subscribe(self.threads_changed)

    def threads_changed(self, changes) -> None:
        self.events.publish(ThreadRowsChanged(str(self.service.root), changes))

    def retire(self) -> None:
        self.sidebar.threads.unsubscribe(self.threads_changed)


class CoordinationAccess(MroDispatch):
    """A validated Core route owns cached access, observations and UI write checks."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        from toad.acp.transcript_reader import CoordinationTranscriptReader

        self.transcripts = CoordinationTranscriptReader(self)
        self.observation: ObservedCommsService | None = None
        self.events = CoreEventStream(self)
        self.revision: WireRevision | None = None
        self.route_observation: RouteObservation = WaitingRoute()
        self.route_task: asyncio.Task[None] | None = None
        self.timer = None
        self.loop: asyncio.AbstractEventLoop | None = None
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
        # Views showing an observed thread's status, by thread name.
        self.thread_owners: WeakKeyDictionary[ThreadStatusOwner, str] = WeakKeyDictionary()
        self.thread_interest: frozenset[str] = frozenset()
        self.views_interest: ObserveViews | None = None
        self.notification_views: WeakKeyDictionary[HistoryNotifications, ReadNotifications] = WeakKeyDictionary()
        self.notification_interest = ObserveNotifications(frozenset())

    @property
    def observed_service(self) -> Comms | None:
        return self.observation.service if self.observation else None

    @property
    def sidebar(self) -> SidebarModel | None:
        return self.observation.sidebar if self.observation else None

    @property
    def service(self) -> Comms:
        """The observed service, opened on first use.

        Reading it is cheap: a changed route is the route check's to detect
        (``check_route``), so views do not capture the route (file reads
        under a lock) whenever they need the service.
        """
        if self.observation is not None:
            return self.observation.service
        return self.open_current()

    def open_current(self) -> Comms:
        """Capture the current route and open (or keep) its service; file I/O."""
        return self.require(RouteSelection.capture())

    def require(self, selected: RouteSelection) -> Comms:
        """The service for ``selected``; a new selection opens it and starts its observation."""
        from agent_comms.comms import wire

        if RouteSelection.capture() != selected:
            raise RouteChanged("Comms route changed before the operation")
        with self.opening:
            observed = self.observation
            if observed is not None and observed.selection == selected:
                return observed.service
            with ExitStack() as acquisition:
                acquisition.enter_context(selected.route.hold_client_route())
                service = wire(selected.route)
                if service.root.resolve() != selected.root or RouteSelection.capture() != selected:
                    raise RouteChanged("Comms route changed while opening the service")
                self.cleanup.enter_context(acquisition.pop_all())
            # Textual runs the models' flushes after the current message,
            # before the next frame is composed.
            self.observation = ObservedCommsService(
                selected, service, SidebarModel(self.app.call_next), ObservationProcess(service.route), self.events)
            self.revision = None
            self.route_observation = WaitingRoute()
        if self.loop is not None:
            # Reader registration belongs to the event loop; require runs on workers too.
            self.loop.call_soon_threadsafe(self.attach, self.observation, observed)
        return service

    def attach(self, observed: ObservedCommsService, previous: ObservedCommsService | None) -> None:
        """Read ``observed``'s results on the loop and tell it the current interest."""
        if previous is not None:
            self.retire(previous)
        if observed is not self.observation:
            self.retire(observed)
            return
        self.loop.add_reader(observed.process.fileno(), self.receive, observed)
        waiters, self.sidebar_waiters = self.sidebar_waiters, []
        for _, waiter in waiters:
            if not waiter.done():
                waiter.set_exception(RouteChanged("Comms service changed before the sidebar was read"))
        self.sidebar_interest = self.sidebar_current = None
        self.thread_owners.clear()
        self.thread_interest = frozenset()
        self.thread_status.clear()
        self.views_interest = None
        self.notification_views.clear()
        self.notification_interest = ObserveNotifications(frozenset())
        self.update_sidebar_interest()
        self.app.session_navigation.declare_views()
        self.events.publish(ObservedServiceChanged())

    def retire(self, observed: ObservedCommsService) -> None:
        observed.retire()
        self.loop.remove_reader(observed.process.fileno())
        observed.process.abandon_reads(StaleRevision("The Comms service was replaced before the read was answered"))
        # Joining the child may wait; it outlives the preparation runtime at app close.
        task = asyncio.ensure_future(asyncio.to_thread(observed.process.close))
        self.retiring.add(task)
        task.add_done_callback(self.retiring.discard)

    def receive(self, observed: ObservedCommsService) -> None:
        if observed is not self.observation:
            return
        try:
            for result in observed.process.results():
                self.dispatch_sync(result, observed)
        except Exception as error:
            # The service failed or exited, or applying its result failed:
            # never keep painting stale state.
            self.loop.remove_reader(observed.process.fileno())
            self.app._handle_exception(error)

    async def read(self, request: AwaitedRead):
        """A read answered in the observation service's process; its exception is raised here."""
        if self.observation is None:
            await self.preparation.run_thread(self.open_current)
        return await self.observation.process.read(request)

    @handles(RevisionObserved)
    def revision_observed(self, result: RevisionObserved, observed: ObservedCommsService) -> None:
        previous = self.revision
        self.revision = result.revision
        if previous is None or result.revision.status_changed_since(previous):
            self.events.publish(CoordinationObserved(result.revision))
        if previous is None or result.revision.external_transcripts_changed_since(previous):
            self.events.publish(ExternalTranscriptChanged())
        if self.sidebar_views:
            # The painted view owns read work, not this source observer.
            self.app.mark_visible()

    @handles(SidebarObserved)
    def sidebar_observed(self, result: SidebarObserved, observed: ObservedCommsService) -> None:
        if result.request != self.sidebar_interest:
            return  # Read for an interest the views have since changed.
        app = self.app
        notice = observed.sidebar.read_marker_notice
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
        for owner, name in tuple(self.thread_owners.items()):
            if name in result.changed and name in result.presentations:
                owner.thread_observed(result.presentations[name])

    @handles(ViewsRetired)
    def views_retired(self, result: ViewsRetired, observed: ObservedCommsService) -> None:
        self.app.session_navigation.views_retired(observed.service.root, result.retired)

    def show_notifications(self, view: HistoryNotifications, read: ReadNotifications | None) -> None:
        """Observe only original messages the views currently show."""
        if read is not None:
            self.notification_views[view] = read
        else:
            self.notification_views.pop(view, None)
        wanted = ObserveNotifications(frozenset(self.notification_views.values()))
        if wanted != self.notification_interest and self.observation is not None:
            self.notification_interest = wanted
            self.observation.process.request(wanted)

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
        request = ObserveViews(threads, channels)
        if request != self.views_interest and self.observation is not None and self.loop is not None:
            self.views_interest = request
            self.observation.process.request(request)

    def sidebar_request(self) -> ObserveSidebar:
        state = self.app.saved_settings.state
        return ObserveSidebar(
            str(self.app.project_dir),
            SETTINGS.sidebar.show_stopped.bind(state).value,
            SETTINGS.sidebar.show_archived.bind(state).value,
        )

    def update_sidebar_interest(self) -> None:
        """Observe the sidebar while a view shows it or a consumer waits for it."""
        observed = self.observation
        if observed is None or self.loop is None:
            return
        wanted = self.sidebar_request() if self.sidebar_views or self.reference_views or self.sidebar_waiters else None
        if wanted != self.sidebar_interest:
            self.sidebar_interest = wanted
            observed.process.request(wanted if wanted is not None else StopSidebar())

    def observe_thread_changes(self, view, scope: tuple[str, str], resume) -> ResourceRelease:
        """Hold the shared model while this native read waits for its own thread."""
        if scope is None:
            raise ValueError("A deferred transcript read requires a bound thread")
        release = ResourceRelease()

        release.callback(view.retire_core, view.observe_core_callback(
            self.events, ThreadRowsChanged, resume, accepts=lambda event: event.affects(scope)))
        release.callback(self.show_sidebar, release, False)
        self.show_sidebar(release, True)
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
        if self.observation is not None:
            try:
                await self.current_sidebar()
            except RouteChanged:
                pass
        return self.reference_context(root)

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

    def show_thread(self, owner: ThreadStatusOwner, name: str | None) -> None:
        """``owner`` shows observed thread ``name``'s status (None: no observed thread)."""
        previous = self.thread_owners.get(owner)
        if name is None:
            self.thread_owners.pop(owner, None)
        else:
            self.thread_owners[owner] = name
        names = frozenset(self.thread_owners.values())
        joined = name is not None and previous != name
        if ((names != self.thread_interest or joined)
                and self.observation is not None and self.loop is not None):
            self.thread_interest = names
            self.observation.process.request(ObserveThreads(names))

    def start(self) -> None:
        """Open the selected service and check the route selection once a second."""
        self.loop = asyncio.get_running_loop()
        if self.observation is not None:
            self.attach(self.observation, None)
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
        if self.observation is not None and self.loop is not None:
            process = self.observation.process
            process.request(StopObserving())
            self.loop.remove_reader(process.fileno())
            self.loop.add_reader(process.fileno(), process.results)

    async def close(self) -> None:
        await self.stop_observing()
        if self.observation is not None and self.loop is not None:
            self.retire(self.observation)
            self.observation = None
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

