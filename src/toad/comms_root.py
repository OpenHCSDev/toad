"""Toad's cached access to the Comms service of the current route.

Core owns route selection and guarded writes (``agent_comms.route_selection``)
and observes its own stores (``agent_comms.ui_model.observation``). This owner
caches the service it opened for one selection, runs one observation process
for it, tells that process what the open views show, and applies its results:
the sidebar model, open threads' status rows and their presentations.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from collections.abc import Callable
from contextlib import ExitStack
from typing import TYPE_CHECKING, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.route_selection import RouteChanged, RouteSelection, run_selected_write
from agent_comms.ui_model.observation import (
    ObservationProcess, ObserveSidebar, ObserveThreads, ObserveViews, RevisionObserved, SidebarObserved,
    ViewsRetired,
    StopSidebar, ThreadsObserved,
)
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import OpenThreadStatus
from toad.core.events import CoreEventStream, CoordinationObserved, OpenTabsChanged

if TYPE_CHECKING:
    from agent_comms.comms import Comms
    from agent_comms.presentation import WireRevision
    from toad.app import ToadApp
    from toad.widgets.observed_thread_activity import ThreadStatusOwner

T = TypeVar("T")

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


class CoordinationAccess(MroDispatch):
    """A validated core route owns cached access, its observation and guarded UI write admission."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.observation: ObservedCommsService | None = None
        self.events = CoreEventStream(self)
        self.revision: WireRevision | None = None
        self.route_stamp: tuple[tuple[int, int, int, int] | None, ...] | None = None
        self.route_task: asyncio.Task[None] | None = None
        self.timer = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.custody = ExitStack()
        self.opening = threading.Lock()
        self.preparation = app.preparation
        self.retiring: set[asyncio.Task[None]] = set()
        self.marking: asyncio.Task[None] | None = None
        # One status row per open thread, whichever service it was read from.
        self.thread_status = OpenThreadStatus(app.call_next)
        # Views showing the sidebar model now, and consumers waiting for current rows.
        self.sidebar_views: WeakSet[object] = WeakSet()
        self.sidebar_waiters: list[tuple[ObserveSidebar, asyncio.Future[None]]] = []
        self.sidebar_interest: ObserveSidebar | None = None
        self.sidebar_current: ObserveSidebar | None = None
        # Views showing an observed thread's status, by thread name.
        self.thread_owners: WeakKeyDictionary[ThreadStatusOwner, str] = WeakKeyDictionary()
        self.thread_interest: frozenset[str] = frozenset()
        self.views_interest: ObserveViews | None = None

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
                acquisition.enter_context(selected.route.admit_client())
                service = wire(selected.route)
                if service.root.resolve() != selected.root or RouteSelection.capture() != selected:
                    raise RouteChanged("Comms route changed while opening the service")
                self.custody.enter_context(acquisition.pop_all())
            # Textual runs the models' flushes after the current message,
            # before the next frame is composed.
            self.observation = ObservedCommsService(
                selected, service, SidebarModel(self.app.call_next), ObservationProcess(service.root))
            self.revision = None
            self.route_stamp = None
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
        for _, waiter in self.sidebar_waiters:
            waiter.set_exception(RouteChanged("Comms service changed before the sidebar was read"))
        self.sidebar_waiters.clear()
        self.sidebar_interest = self.sidebar_current = None
        self.thread_owners.clear()
        self.thread_interest = frozenset()
        self.thread_status.clear()
        self.views_interest = None
        self.update_sidebar_interest()
        self.app.session_navigation.declare_views()

    def retire(self, observed: ObservedCommsService) -> None:
        self.loop.remove_reader(observed.process.fileno())
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

    @handles(RevisionObserved)
    def revision_observed(self, result: RevisionObserved, observed: ObservedCommsService) -> None:
        self.revision = result.revision
        self.events.publish(CoordinationObserved(result.revision))
        if self.sidebar_views and (self.marking is None or self.marking.done()):
            # A shown sidebar acknowledges the painted native cursor, as each
            # sidebar read did before; the next observation includes it.
            self.marking = asyncio.ensure_future(self.app.mark_visible_thread_read())

    @handles(SidebarObserved)
    def sidebar_observed(self, result: SidebarObserved, observed: ObservedCommsService) -> None:
        if result.request != self.sidebar_interest:
            return  # Read for an interest the views have since changed.
        app = self.app
        notice = observed.sidebar.read_marker_notice
        tabs = app.open_tabs
        observed.sidebar.apply(result.snapshot, result.derived)
        self.sidebar_current = result.request
        if result.snapshot.read_marker_notice and result.snapshot.read_marker_notice != notice:
            app.notify(result.snapshot.read_marker_notice, title="Read positions", severity="warning")
        if app.open_tabs != tabs:
            app.events.publish(OpenTabsChanged())
        waiting = [(request, waiter) for request, waiter in self.sidebar_waiters if request != result.request]
        for request, waiter in self.sidebar_waiters:
            if request == result.request and not waiter.done():
                waiter.set_result(None)
        self.sidebar_waiters = waiting
        self.update_sidebar_interest()

    @handles(ThreadsObserved)
    def threads_observed(self, result: ThreadsObserved, observed: ObservedCommsService) -> None:
        self.thread_status.observed(result)
        for owner, name in tuple(self.thread_owners.items()):
            if name in result.presentations:
                owner.thread_observed(result.presentations[name])

    @handles(ViewsRetired)
    def views_retired(self, result: ViewsRetired, observed: ObservedCommsService) -> None:
        self.app.session_navigation.views_retired(observed.service.root, result.retired)

    def show_views(self, threads: frozenset, channels: frozenset[str]) -> None:
        """The thread incarnations and channel views open on the observed root."""
        request = ObserveViews(threads, channels)
        if request != self.views_interest and self.observation is not None and self.loop is not None:
            self.views_interest = request
            self.observation.process.request(request)

    def sidebar_request(self) -> ObserveSidebar:
        settings = self.app.settings.sidebar
        return ObserveSidebar(str(self.app.project_dir), settings.show_stopped, settings.show_archived)

    def update_sidebar_interest(self) -> None:
        """Observe the sidebar while a view shows it or a consumer waits for it."""
        observed = self.observation
        if observed is None or self.loop is None:
            return
        wanted = self.sidebar_request() if self.sidebar_views or self.sidebar_waiters else None
        if wanted != self.sidebar_interest:
            self.sidebar_interest = wanted
            observed.process.request(wanted if wanted is not None else StopSidebar())

    def show_sidebar(self, view: object, shown: bool) -> None:
        """A view started or stopped showing the sidebar model."""
        if shown:
            self.sidebar_views.add(view)
        else:
            self.sidebar_views.discard(view)
        self.update_sidebar_interest()

    async def current_sidebar(self) -> None:
        """Wait until the sidebar model shows the current stores, for a consumer that reads it now."""
        request = self.sidebar_request()
        if self.sidebar_interest == request and self.sidebar_current == request:
            return  # Observed now: every store change is delivered.
        waiter = asyncio.get_running_loop().create_future()
        self.sidebar_waiters.append((request, waiter))
        self.update_sidebar_interest()
        await waiter

    def show_thread(self, owner: ThreadStatusOwner, name: str | None) -> None:
        """``owner`` shows observed thread ``name``'s status (None: no observed thread)."""
        if name is None:
            self.thread_owners.pop(owner, None)
        else:
            self.thread_owners[owner] = name
        names = frozenset(self.thread_owners.values())
        if names != self.thread_interest and self.observation is not None and self.loop is not None:
            self.thread_interest = names
            self.observation.process.request(ObserveThreads(names))

    def start(self) -> None:
        """Open the selected service and check the route selection once a second."""
        self.loop = asyncio.get_running_loop()
        if self.observation is not None:
            self.attach(self.observation, None)
        self.timer = self.app.set_interval(ROUTE_CHECK_SECONDS, self.check_route)
        self.check_route()

    async def close(self) -> None:
        if self.timer is not None:
            self.timer.stop()
        if self.route_task is not None:
            self.route_task.cancel()
            await asyncio.gather(self.route_task, return_exceptions=True)
        if self.observation is not None and self.loop is not None:
            self.retire(self.observation)
            self.observation = None
        await asyncio.gather(*self.retiring, return_exceptions=True)
        self.custody.close()

    def current_route_stamp(self) -> tuple[tuple[int, int, int, int] | None, ...]:
        from agent_comms.active_route import active_route_path
        from agent_comms.store_files import file_revision

        service = self.observed_service
        return (file_revision(active_route_path()),
                file_revision(service.root / "bus_meta.json") if service else None)

    async def route_changed(self) -> bool:
        stamp = await self.preparation.run_thread(self.current_route_stamp)
        return self.route_stamp is None or stamp[0] != self.route_stamp[0]

    def check_route(self) -> None:
        if self.route_task is None or self.route_task.done():
            self.route_task = asyncio.create_task(self.observe_route())

    async def observe_route(self) -> None:
        """A changed route selection opens (and observes) the newly selected service."""
        try:
            stamp = await self.preparation.run_thread(self.current_route_stamp)
            if stamp == self.route_stamp:
                return
            await self.preparation.run_thread(self.open_current)
            stamp = await self.preparation.run_thread(self.current_route_stamp)
        except (OSError, ValueError, RuntimeError):
            # A route publication may be replacing its marker. Views still
            # learn of it and keep their own route fences; the next check
            # validates again.
            stamp = None
        self.route_stamp = stamp
        self.events.publish(CoordinationObserved(self.revision))

    def write(self, selected: RouteSelection, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. The existing
        # core route lock is held through the operation; no second lock/store.
        return run_selected_write(selected.root, operation, *args, implicit=selected.implicit, **kwargs)

