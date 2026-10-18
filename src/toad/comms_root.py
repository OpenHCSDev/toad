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
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from typing import TYPE_CHECKING, TypeVar
from pathlib import Path
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.active_route import active_route_path
from agent_comms.coordination_errors import StaleRevision
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.presentation import MessageNotification, NoRevision, ReadState
from agent_comms.private_path import FileRevision
from agent_comms.route_selection import RouteChanged, RouteSelection, run_selected_write
from agent_comms.ui_model.observation import (
    ObserveNotifications, NotificationsObserved, NotificationsUnreadable, ReadNotifications,
    ObservationProcess, ObserveSidebar, ObserveThreads, ObserveViews, RevisionObserved,
    SidebarObserved, SidebarUnreadable, ViewsRetired,
    StopObserving, StopSidebar, ThreadsObserved,
)
from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation
from agent_comms.ui_model.status import OpenThreadStatus
from toad.core.events import CoreEventStream, CoordinationObserved, ExternalTranscriptChanged, OpenTabsChanged, LinkContextChanged, ObservedServiceChanged, ThreadRowsChanged
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
class NotObserving:
    access: CoordinationAccess

    def observed(self) -> Observing:
        return self.access.open_current()

    def uses(self, service) -> bool:
        return False

    def observes(self, root) -> bool:
        return False
    def tabs(self, sessions):
        return {entry.mode: entry.unobserved_tab() for entry in sessions.members}
    def route_stamp(self):
        return (FileRevision.capture(active_route_path()),)
    async def observe_route(self, access):
        observed = await access.preparation.run_thread(access.open_current)
        return await observed.observe_route(access)
    def require(self, access, selected):
        return access.open_selected(selected)
    def retire(self, access):
        pass
    def notifications(self, access, wanted):
        pass
    def sidebar_interest(self, access):
        pass
    def references_for(self, root):
        return PendingReferences(root)
    async def current_references(self, access, root):
        return access.reference_context(root)
    def stop(self):
        pass


@dataclass(frozen=True)
class Observing:
    selection: RouteSelection
    service: Comms = field()
    sidebar: SidebarModel = field()
    process: ObservationProcess = field(compare=False)
    loop: asyncio.AbstractEventLoop
    access: CoordinationAccess = field(compare=False)
    subscriptions: ResourceRelease = field(default_factory=ResourceRelease, compare=False)

    def observes(self, root) -> bool:
        return self.service.root == Path(root).resolve()

    def tabs(self, sessions):
        return {entry.mode: entry.tab(sessions, self) for entry in sessions.members}

    def observed(self) -> Observing:
        return self

    def current(self) -> bool:
        return self is self.access.observation

    def show_sidebar(self, view) -> None:
        if self.current():
            view.bind_observation(self)

    def uses(self, service) -> bool:
        return self.service is service

    async def write_order(self, access, root, channel, order):
        if root is not None and not self.observes(root):
            raise ValueError("Comms route changed before sorting")
        return await access.preparation.run_thread(
            access.write, self.selection, order.store_channel_order, self.service.channels, channel)

    def route_stamp(self):
        return (FileRevision.capture(active_route_path()),
                FileRevision.capture(self.service.root / "bus_meta.json"))

    async def observe_route(self, access):
        root = str(self.service.root)
        previous_references = access.reference_context(root)
        stamp = await access.preparation.run_thread(self.route_stamp)
        if stamp == access.route_observation.stamp:
            return False
        await access.preparation.run_thread(access.open_current)
        stamp = await access.preparation.run_thread(access.observation.route_stamp)
        access.route_observation = ObservedRoute(stamp)
        if previous_references != access.reference_context(root):
            access.events.publish(LinkContextChanged())
        return True

    def require(self, access, selected):
        return self if self.selection == selected else access.open_selected(selected)

    def attach(self, access, previous):
        previous.retire(access)
        if not self.current():
            self.retire(access)
            return
        self.loop.add_reader(self.process.fileno(), self.receive, access)
        waiters, access.sidebar_waiters = access.sidebar_waiters, []
        for _, waiter in waiters:
            if not waiter.done():
                waiter.set_exception(RouteChanged("Comms service changed before the sidebar was read"))
        access.sidebar_interest = access.sidebar_current = None
        access.thread_status.clear()
        access.views_interest = None
        access.notification_views.clear()
        access.notification_outcomes.clear()
        access.notification_interest = ObserveNotifications(frozenset())
        self.sidebar_interest(access)
        self.thread_interest(access)
        self.subscriptions.enter_context(access.app.events.subscribe(OpenTabsChanged, self.views_changed))
        self.views_changed()
        access.events.publish(ObservedServiceChanged())

    def retire(self, access):
        self.subscriptions.close()
        self.loop.remove_reader(self.process.fileno())
        self.process.abandon_reads(StaleRevision("The Comms service was replaced before the read was answered"))
        task = asyncio.ensure_future(asyncio.to_thread(self.process.close))
        access.retiring.add(task)
        task.add_done_callback(access.retiring.discard)

    def receive(self, access):
        if not self.current():
            return
        try:
            for result in self.process.results():
                access.dispatch_sync(result, self)
        except (OSError, ValueError, RuntimeError) as error:
            self.loop.remove_reader(self.process.fileno())
            access.app._handle_exception(error)

    def notifications(self, access, wanted):
        if wanted != access.notification_interest:
            access.notification_interest = wanted
            self.process.request(wanted)

    def views_changed(self, event=None, subscription=None):
        access, root = self.access, str(self.service.root)
        threads, channels = set(), set()
        for member in access.app.session_navigation.members:
            threads.update(identity for owner, identity in member.original_threads(access.app.session_navigation) if owner == root)
            channels.update(target for owner, target in member.original_channels() if owner == root)
        request = ObserveViews(frozenset(threads), frozenset(channels))
        if request != access.views_interest:
            access.views_interest = request
            self.process.request(request)

    def sidebar_interest(self, access):
        wanted = access.sidebar_request() if access.sidebar_views or access.reference_views or access.sidebar_waiters else None
        if wanted != access.sidebar_interest:
            access.sidebar_interest = wanted
            self.process.request(wanted if wanted is not None else StopSidebar())

    def references_for(self, root):
        return self.sidebar.observation.references_for(root)

    async def current_references(self, access, root):
        try:
            await access.current_sidebar()
        except RouteChanged:
            pass
        return access.reference_context(root)

    def thread_interest(self, access):
        self.process.request(ObserveThreads(access.events.observed_threads(str(self.service.root))))

    def stop(self):
        process = self.process
        process.request(StopObserving())
        self.loop.remove_reader(process.fileno())
        self.loop.add_reader(process.fileno(), process.results)


type Observation = NotObserving | Observing


class CoordinationAccess(MroDispatch):
    """A validated Core route owns cached access, observations and UI write checks."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        from toad.acp.transcript_reader import CoordinationTranscriptReader

        self.transcripts = CoordinationTranscriptReader(self)
        self.observation: Observation = NotObserving(self)
        self.events = CoreEventStream(self)
        self.revision: ReadState = NoRevision()
        self.route_observation: RouteObservation = RouteObservation()
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
        self.notification_outcomes: dict[ReadNotifications, Mapping[tuple[int, str], tuple[MessageNotification, ...]]] = {}
        self.notification_interest = ObserveNotifications(frozenset())

    def open_current(self) -> Observing:
        """Capture the current route and open (or keep) its service; file I/O."""
        return self.require(RouteSelection.capture())

    def require(self, selected: RouteSelection) -> Observing:
        """The service for ``selected``; a new selection opens it and starts its observation."""
        if RouteSelection.capture() != selected:
            raise RouteChanged("Comms route changed before the operation")
        with self.opening:
            return self.observation.require(self, selected)

    def open_selected(self, selected: RouteSelection) -> Observing:
        from agent_comms.comms import wire

        previous = self.observation
        with ExitStack() as acquisition:
            acquisition.enter_context(selected.route.hold_client_route())
            service = wire(selected.route)
            if service.root.resolve() != selected.root or RouteSelection.capture() != selected:
                raise RouteChanged("Comms route changed while opening the service")
            self.cleanup.enter_context(acquisition.pop_all())
        observed = Observing(
            selected, service, SidebarModel(self.app.call_next), ObservationProcess(service.route),
            self.app.running_loop, self)
        self.observation = observed
        self.revision = NoRevision()
        self.route_observation = RouteObservation()
        observed.loop.call_soon_threadsafe(observed.attach, self, previous)
        return observed

    @handles(RevisionObserved)
    def revision_observed(self, result: RevisionObserved, observed: Observing) -> None:
        previous = self.revision
        self.revision = result.revision
        if previous.status_changed_since(result.revision):
            self.events.publish(CoordinationObserved(result.revision))
        if previous.external_transcripts_changed_since(result.revision):
            self.events.publish(ExternalTranscriptChanged())

    @handles(SidebarObserved)
    def sidebar_observed(self, result: SidebarObserved, observed: Observing) -> None:
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
    def sidebar_unreadable(self, result: SidebarUnreadable, observed: Observing) -> None:
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
        self.observation.sidebar_interest(self)
        return answered_waiters

    @handles(ThreadsObserved)
    def threads_observed(self, result: ThreadsObserved, observed: Observing) -> None:
        self.thread_status.observed(result)
        self.events.publish(ThreadRowsChanged(str(observed.service.root), result.changed))

    @handles(ViewsRetired)
    def views_retired(self, result: ViewsRetired, observed: Observing) -> None:
        self.app.session_navigation.views_retired(observed.service.root, result.retired)

    def show_notifications(self, view: HistoryNotifications, read: ReadNotifications) -> None:
        self.notification_views[view] = read
        if read in self.notification_outcomes:
            view.notifications_observed(self.notification_outcomes[read])
        self._request_interest()

    def stop_notifications(self, view: HistoryNotifications) -> None:
        self.notification_views.pop(view, None)
        self._request_interest()

    def _request_interest(self) -> None:
        wanted = ObserveNotifications(frozenset(self.notification_views.values()))
        for previous in self.notification_outcomes.keys() - wanted.reads:
            self.notification_outcomes.pop(previous)
        self.observation.notifications(self, wanted)

    @handles(NotificationsObserved)
    def notifications_observed(self, result: NotificationsObserved, observed: Observing) -> None:
        if result.request not in self.notification_views.values():
            return
        self.notification_outcomes[result.request] = result.outcomes
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_observed(result.outcomes)

    @handles(NotificationsUnreadable)
    def notifications_unreadable(self, result: NotificationsUnreadable, observed: Observing) -> None:
        self.notification_outcomes.pop(result.request, None)
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_failed(result.error)

    def sidebar_request(self) -> ObserveSidebar:
        state = self.app.saved_settings.state
        return ObserveSidebar(
            str(self.app.project_dir),
            SETTINGS.sidebar.show_stopped.bind(state).value,
            SETTINGS.sidebar.show_archived.bind(state).value,
        )

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
        self.observation.sidebar_interest(self)

    def show_references(self, view, shown):
        if shown:
            self.reference_views.add(view)
        else:
            self.reference_views.discard(view)
        self.observation.sidebar_interest(self)

    def reference_context(self, root):
        return self.route_observation.references_for(self.observation, root)

    async def current_sidebar(self) -> SidebarObservation:
        """Return the source's current answer, including a failed observation."""
        observed = await self.preparation.run_thread(self.observation.observed)
        request = self.sidebar_request()
        if self.sidebar_interest == request and self.sidebar_current == request:
            return observed.sidebar.observation
        waiter = asyncio.get_running_loop().create_future()
        pending = request, waiter
        self.sidebar_waiters.append(pending)
        self.observation.sidebar_interest(self)
        try:
            return await waiter
        finally:
            if pending in self.sidebar_waiters:
                self.sidebar_waiters.remove(pending)
                self.observation.sidebar_interest(self)

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
        self.observation.stop()

    async def close(self) -> None:
        await self.stop_observing()
        self.observation.retire(self)
        self.observation = NotObserving(self)
        await asyncio.gather(*self.retiring, return_exceptions=True)
        self.cleanup.close()

    async def route_changed(self) -> bool:
        stamp = await self.preparation.run_thread(self.observation.route_stamp)
        return self.route_observation.changed(stamp)

    def check_route(self) -> None:
        if self.route_task is None or self.route_task.done():
            self.route_task = asyncio.create_task(self.observe_route())

    async def observe_route(self) -> None:
        """A changed route selection opens (and observes) the newly selected service."""
        try:
            if not await self.observation.observe_route(self):
                return
        except (OSError, ValueError, RuntimeError) as error:
            self.route_observation = FailedRoute(error)
            self.events.publish(LinkContextChanged())
            if self.reference_views:
                self.route_observation.report(self.app)
        self.events.publish(CoordinationObserved(self.revision))

    def write(self, selected: RouteSelection, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. The existing
        # core route lock is held through the operation; no second lock/store.
        return run_selected_write(selected.root, operation, *args, implicit=selected.implicit, **kwargs)

