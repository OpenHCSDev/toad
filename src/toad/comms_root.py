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
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.coordination_errors import StaleRevision
from agent_comms.display_references import PendingReferences, UnavailableReferences
from agent_comms.errors import RouteChangedError
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.presentation import MessageNotification, NoRevision, ReadState
from agent_comms.revision_views import ExternalTranscriptsView, StatusView
from agent_comms.route_selection import RouteSelection, run_selected_write
from agent_comms.ui_model.observation import (
    NotificationsObserved,
    NotificationsUnreadable,
    ObservationProcess,
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
    CoordinationObserved,
    CoreEventStream,
    ExternalTranscriptChanged,
    LinkContextChanged,
    ObservedServiceChanged,
    OpenTabsChanged,
    ThreadRowsChanged,
)
from toad.preferences import SETTINGS
from toad.resource_release import ResourceRelease

if TYPE_CHECKING:
    from agent_comms.comms import Comms

    from toad.app import ToadApp
    from toad.widgets.message_notifications import HistoryNotifications
    from toad.widgets.sidebar_tree import SidebarModelView

T = TypeVar("T")

ROUTE_CHECK_SECONDS = 1.0


@dataclass(frozen=True)
class UnselectedRoute:
    """Route capture failed before a validated selection existed."""


@dataclass(frozen=True, kw_only=True)
class Observation:
    access: CoordinationAccess = field(compare=False)
    subscriptions: ResourceRelease = field(
        default_factory=ResourceRelease, compare=False
    )
    # View updates end before the views close; `subscriptions` retires the observation after them.
    updates: ResourceRelease = field(default_factory=ResourceRelease, compare=False)

    def observed(self):
        return self

    def is_current(self) -> bool:
        return self is self.access.observation

    def observes(self, root) -> bool:
        return False

    def uses(self, service) -> bool:
        return False

    def tab(self, entry, sessions):
        return entry.unobserved_tab()

    def tabs(self, sessions):
        return {entry.mode: self.tab(entry, sessions) for entry in sessions.members}

    def require(self, access, selected):
        return access.open_selected(selected)

    def references_for(self, root):
        return PendingReferences(root)

    async def current_references(self, access, root):
        return access.reference_context(root)

    def failed(self, error, selected):
        failed = FailedObservation(error, selected, access=self.access)
        if failed == self:
            return self
        self.access.observation = failed
        self.access.app.running_loop.call_soon_threadsafe(
            failed.attach, self.access, self
        )
        return failed

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
                waiter.set_exception(
                    RouteChangedError("Comms service changed before the sidebar was read")
                )
        access.revision = NoRevision()
        access.sidebar_interest = access.sidebar_current = None
        access.thread_status.clear()
        access.views_interest = None
        access.notification_views.clear()
        access.notification_outcomes.clear()
        access.notification_interest = ObserveNotifications(frozenset())
        self.activate(access)
        access.events.publish(ObservedServiceChanged())


class NotObserving(Observation):
    def observed(self):
        return self.access.open_current()


@dataclass(frozen=True, eq=False)
class FailedObservation(Observation):
    error: Exception = field(compare=False, repr=False)
    selection: RouteSelection | UnselectedRoute

    def __eq__(self, other: object) -> bool:
        # Exceptions declare their type, constructor fields and extra state through
        # reconstruction; OSError includes filenames that are absent from args.
        return (
            isinstance(other, FailedObservation)
            and self.selection == other.selection
            and self.error.__reduce__() == other.error.__reduce__()
        )

    @property
    def service(self):
        raise self.error

    @property
    def sidebar(self):
        raise self.error

    async def write_order(self, access, root, channel, order):
        raise self.error

    def references_for(self, root):
        return UnavailableReferences(root, str(self.error))

    def show_sidebar(self, view):
        view.bind_failed_observation(self)

    def activate(self, access):
        self.observe_sidebar(None)

    def observe_sidebar(self, wanted):
        access = self.access
        for view in tuple(access.sidebar_views):
            self.show_sidebar(view)

    def observe_notifications(self, wanted):
        for view in tuple(self.access.notification_views):
            view.notifications_failed(self.error)

    def thread_interest(self, access):
        access.app.show_error(self.error, "Thread status unavailable")


@dataclass(frozen=True)
class Observing(Observation):
    selection: RouteSelection
    service: Comms = field()
    sidebar: SidebarModel = field()
    process: ObservationProcess = field(compare=False)
    loop: asyncio.AbstractEventLoop

    def observes(self, root) -> bool:
        return self.service.root == Path(root).resolve()

    def tab(self, entry, sessions):
        return entry.tab(sessions, self)

    def show_sidebar(self, view) -> None:
        if self.is_current():
            view.bind_observation(self)

    def uses(self, service) -> bool:
        return self.service is service

    async def write_order(self, access, root, channel, order):
        if root is not None and not self.observes(root):
            raise ValueError("Comms route changed before sorting")
        return await access.preparation.run_thread(
            access.write,
            self.selection,
            order.store_channel_order,
            self.service.channels,
            channel,
        )

    def require(self, access, selected):
        return self if self.selection == selected else access.open_selected(selected)

    def activate(self, access):
        self.loop.add_reader(self.process.fileno(), self.receive, access)
        access.update_sidebar_interest()
        self.thread_interest(access)
        self.updates.callback(self.answer_reads)
        self.updates.enter_context(
            access.app.events.subscribe(OpenTabsChanged, self.views_changed)
        )
        self.subscriptions.enter_context(self.updates)
        self.views_changed()

    def answer_reads(self):
        self.process.request(StopObserving())
        self.loop.remove_reader(self.process.fileno())
        self.loop.add_reader(self.process.fileno(), self.process.results)

    def stop_updates(self) -> AnsweringReads:
        super().stop_updates()
        return AnsweringReads(
            self.selection,
            self.service,
            self.sidebar,
            self.process,
            self.loop,
            access=self.access,
            subscriptions=self.subscriptions,
            updates=self.updates,
        )

    def retire(self, access):
        self.loop.remove_reader(self.process.fileno())
        self.process.abandon_reads(
            StaleRevision("The Comms service was replaced before the read was answered")
        )
        task = asyncio.ensure_future(asyncio.to_thread(self.process.close))
        access.retiring.add(task)
        task.add_done_callback(access.retiring.discard)

    def receive(self, access):
        if not self.is_current():
            return
        try:
            for result in self.process.results():
                access.dispatch_sync(result, self)
        except (OSError, ValueError, RuntimeError) as error:
            self.loop.remove_reader(self.process.fileno())
            access.app._handle_exception(error)

    def views_changed(self, event=None, subscription=None):
        access, root = self.access, str(self.service.root)
        threads, channels = set(), set()
        for member in access.app.session_navigation.members:
            threads.update(
                identity
                for owner, identity in member.original_threads(
                    access.app.session_navigation
                )
                if owner == root
            )
            channels.update(
                target for owner, target in member.original_channels() if owner == root
            )
        request = ObserveViews(frozenset(threads), frozenset(channels))
        if request != access.views_interest:
            access.views_interest = request
            self.process.request(request)

    def references_for(self, root):
        return self.sidebar.observation.references_for(root)

    async def current_references(self, access, root):
        try:
            await access.current_sidebar()
        except RouteChangedError:
            return await access.observation.current_references(access, root)
        return access.reference_context(root)

    def thread_interest(self, access):
        self.process.request(
            ObserveThreads(access.events.observed_threads(str(self.service.root)))
        )

    def observe_sidebar(self, wanted):
        self.process.request(wanted if wanted is not None else StopSidebar())

    def observe_notifications(self, wanted):
        self.process.request(wanted)


class AnsweringReads(Observing):
    """Interests have ended; acquired reads keep their process and release owners."""

    def stop_updates(self) -> AnsweringReads:
        return self

    def views_changed(self, event=None, subscription=None):
        pass

    def thread_interest(self, access):
        pass

    def observe_sidebar(self, wanted):
        pass

    def observe_notifications(self, wanted):
        pass


class CoordinationAccess(MroDispatch):
    """A validated Core route owns cached access, observations and UI write checks."""

    def __init__(self, app: ToadApp) -> None:
        from agent_comms.launch_root import LaunchRoot

        self.app = app
        self.launch_root = LaunchRoot.current()
        from toad.acp.transcript_reader import CoordinationTranscriptReader

        self.transcripts = CoordinationTranscriptReader(self)
        self.observation: Observation = NotObserving(access=self)
        self.events = CoreEventStream(self)
        self.revision: ReadState = NoRevision()
        self.route_task: asyncio.Task[None] | None = None
        self.timer = None
        self.cleanup = ExitStack()
        self.opening = threading.RLock()
        self.preparation = app.preparation
        self.retiring: set[asyncio.Task[None]] = set()
        # One status row per open thread, whichever service it was read from.
        self.thread_status = OpenThreadStatus(app.call_next)
        # Views showing the sidebar model now, and consumers waiting for current rows.
        self.sidebar_views: WeakSet[SidebarModelView] = WeakSet()
        self.reference_views: WeakSet[object] = WeakSet()
        self.sidebar_waiters: list[
            tuple[ObserveSidebar, asyncio.Future[SidebarObservation]]
        ] = []
        self.sidebar_interest: ObserveSidebar | None = None
        self.sidebar_current: ObserveSidebar | None = None
        self.views_interest: ObserveViews | None = None
        self.notification_views: WeakKeyDictionary[
            HistoryNotifications, ReadNotifications
        ] = WeakKeyDictionary()
        self.notification_outcomes: dict[
            ReadNotifications, Mapping[tuple[int, str], tuple[MessageNotification, ...]]
        ] = {}
        self.notification_interest = ObserveNotifications(frozenset())

    def open_current(self) -> Observing | FailedObservation:
        """Capture the current route and open its service, or expose the opening error."""
        with self.opening:
            selected: RouteSelection | UnselectedRoute = UnselectedRoute()
            try:
                selected = RouteSelection.capture(self.launch_root.path)
                return self.require(selected)
            except (OSError, ValueError, RuntimeError) as error:
                return self.observation.failed(error, selected)

    def require(self, selected: RouteSelection) -> Observing:
        """The service for ``selected``; a new selection opens it and starts its observation."""
        if RouteSelection.capture() != selected:
            raise RouteChangedError("Comms route changed before the operation")
        with self.opening:
            return self.observation.require(self, selected)

    def open_selected(self, selected: RouteSelection) -> Observing:
        from agent_comms.comms import wire

        previous = self.observation
        with ExitStack() as acquisition:
            acquisition.enter_context(selected.route.hold_client_route())
            service = wire(selected.route)
            if (
                service.root.resolve() != selected.root
                or RouteSelection.capture() != selected
            ):
                raise RouteChangedError("Comms route changed while opening the service")
            observed = Observing(
                selected,
                service,
                SidebarModel(self.app.call_next),
                ObservationProcess(service.route),
                self.app.running_loop,
                access=self,
            )
            self.cleanup.enter_context(acquisition.pop_all())
        observed.subscriptions.callback(observed.retire, self)
        self.observation = observed
        observed.loop.call_soon_threadsafe(observed.attach, self, previous)
        return observed

    @handles(RevisionObserved)
    def revision_observed(self, result: RevisionObserved, observed: Observing) -> None:
        previous = self.revision
        self.revision = result.revision
        if result.revision.changed_since(StatusView(), previous):
            self.events.publish(CoordinationObserved(result.revision))
        if result.revision.changed_since(ExternalTranscriptsView(), previous):
            self.events.publish(ExternalTranscriptChanged())

    @handles(SidebarObserved)
    def sidebar_observed(self, result: SidebarObserved, observed: Observing) -> None:
        if result.request != self.sidebar_interest:
            return  # Read for an interest the views have since changed.
        app = self.app
        notice = observed.sidebar.observation.read_marker_notice()
        modes = app.tab_order.names
        previous_references = self.reference_context(str(observed.service.root))
        observed.sidebar.apply(result.snapshot, result.derived)
        self.present_sidebar()
        if previous_references != self.reference_context(str(observed.service.root)):
            self.events.publish(LinkContextChanged())
        self.sidebar_current = result.request
        result.snapshot.read_marker_notice.notify_if_new(
            notice,
            lambda text: app.notify(text, title="Read positions", severity="warning"),
        )
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
    def sidebar_unreadable(
        self, result: SidebarUnreadable, observed: Observing
    ) -> None:
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
        """Present the current backend answer even when its row set stays empty."""
        for view in tuple(self.sidebar_views):
            view.present()

    def take_sidebar_waiters(
        self, answered: ObserveSidebar
    ) -> list[asyncio.Future[SidebarObservation]]:
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
        self.events.publish(
            ThreadRowsChanged(names=result.changed, root=str(observed.service.root))
        )

    @handles(ViewsRetired)
    def views_retired(self, result: ViewsRetired, observed: Observing) -> None:
        self.app.session_navigation.views_retired(observed.service.root, result.retired)

    def show_notifications(
        self, view: HistoryNotifications, read: ReadNotifications
    ) -> None:
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
        if wanted != self.notification_interest:
            observed = self.observation.observed()
            self.notification_interest = wanted
            observed.observe_notifications(wanted)

    @handles(NotificationsObserved)
    def notifications_observed(
        self, result: NotificationsObserved, observed: Observing
    ) -> None:
        if result.request not in self.notification_views.values():
            return
        self.notification_outcomes[result.request] = result.outcomes
        for view, request in tuple(self.notification_views.items()):
            if result.request == request:
                view.notifications_observed(result.outcomes)

    @handles(NotificationsUnreadable)
    def notifications_unreadable(
        self, result: NotificationsUnreadable, observed: Observing
    ) -> None:
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

    def update_sidebar_interest(self) -> None:
        wanted = (
            self.sidebar_request()
            if self.sidebar_views or self.reference_views or self.sidebar_waiters
            else None
        )
        if wanted != self.sidebar_interest:
            observed = self.observation.observed()
            self.sidebar_interest = wanted
            observed.observe_sidebar(wanted)

    def show_sidebar(self, view: SidebarModelView, shown: bool) -> None:
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
        await self.stop_observing()
        self.observation.subscriptions.close()
        self.observation = NotObserving(access=self)
        await asyncio.gather(*self.retiring, return_exceptions=True)
        self.cleanup.close()

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

    def write(
        self,
        selected: RouteSelection,
        operation: Callable[..., T],
        *args: object,
        **kwargs: object,
    ) -> T:
        # This method runs in the same worker as the actual sink. The existing
        # core route lock is held through the operation; no second lock/store.
        return run_selected_write(selected.root, operation, *args, **kwargs)
