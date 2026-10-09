"""Toad's cached access to the Comms service of the current route.

Core owns route selection and guarded writes (``agent_comms.route_selection``);
this view only caches the service it opened for one selection, and keeps that
service's sidebar presentation model current for every view that renders it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Callable
from contextlib import ExitStack
from typing import TYPE_CHECKING, TypeVar
from weakref import WeakSet
from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision
from agent_comms.route_selection import RouteChanged, RouteSelection, root_is_current, run_selected_write
from agent_comms.ui_model.sidebar import SidebarModel
from toad.core.events import CoreEventStream, CoordinationObserved, OpenTabsChanged

if TYPE_CHECKING:
    from agent_comms.comms import Comms
    from agent_comms.presentation import WireRevision
    from toad.app import ToadApp

T = TypeVar("T")


@dataclass(frozen=True)
class ObservedCommsService:
    """One opened service and the sidebar model every view of it renders."""

    selection: RouteSelection
    service: Comms
    sidebar: SidebarModel


@dataclass(frozen=True)
class SidebarRead:
    """What the sidebar model was last derived from."""

    observed: ObservedCommsService
    revision: WireRevision
    filters: tuple[bool, bool]


class CoordinationAccess:
    """A validated core route owns cached access and guarded UI write admission."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.observation: ObservedCommsService | None = None
        self.events = CoreEventStream(self)
        self.revision: WireRevision | None = None
        self.route_stamp: tuple[tuple[int, int, int, int] | None, ...] | None = None
        self.task: asyncio.Task[None] | None = None
        self.timer = None
        self.custody = ExitStack()
        self.preparation = app.preparation
        self.sidebar_read: SidebarRead | None = None
        self.sidebar_task: asyncio.Task[None] | None = None
        self.sidebar_requested = False
        # Views showing the sidebar model now; observed changes are read only for them.
        self.sidebar_views: WeakSet[object] = WeakSet()

    @property
    def observed_service(self) -> Comms | None:
        return self.observation.service if self.observation else None

    @property
    def sidebar(self) -> SidebarModel | None:
        return self.observation.sidebar if self.observation else None

    @property
    def service(self) -> Comms:
        return self.require(RouteSelection.capture())

    def require(self, selected: RouteSelection) -> Comms:
        from agent_comms.comms import wire

        if RouteSelection.capture() != selected:
            raise RouteChanged("Comms route changed before the operation")
        observed = self.observation
        if observed is not None and observed.selection == selected:
            return observed.service
        with ExitStack() as acquisition:
            acquisition.enter_context(selected.route.admit_client())
            service = wire(selected.route)
            if service.root.resolve() != selected.root or RouteSelection.capture() != selected:
                raise RouteChanged("Comms route changed while opening the service")
            self.custody.enter_context(acquisition.pop_all())
        # Textual runs the model's flush after the current message, before
        # the next frame is composed.
        self.observation = ObservedCommsService(selected, service, SidebarModel(self.app.call_next))
        self.revision = None
        self.route_stamp = None
        return service

    def show_sidebar(self, view: object, shown: bool) -> None:
        """A view started or stopped showing the sidebar model; a new viewer catches up."""
        if not shown:
            self.sidebar_views.discard(view)
        elif view not in self.sidebar_views:
            self.sidebar_views.add(view)
            self.request_sidebar()

    async def current_sidebar(self) -> None:
        """Bring the sidebar model up to the current stores for a consumer that reads it now."""
        self.request_sidebar()
        await asyncio.shield(self.sidebar_task)

    def request_sidebar(self) -> None:
        """Re-derive the sidebar model if its stores or filters changed; one read at a time."""
        if self.sidebar_task is not None and not self.sidebar_task.done():
            self.sidebar_requested = True
            return
        self.sidebar_task = asyncio.create_task(self.read_sidebar())

    async def read_sidebar(self) -> None:
        app = self.app
        self.sidebar_requested = True
        while self.sidebar_requested:
            self.sidebar_requested = False
            observed = self.observation
            if observed is None:
                return
            service = observed.service
            filters = (app.settings.sidebar.show_stopped, app.settings.sidebar.show_archived)
            read = self.sidebar_read
            worktree = str(app.project_dir)

            def capture():
                # One worker hop: snapshot and row derivation inspect process
                # identity and stores, never on the UI thread.
                revision = service.views.revision()
                if (read is not None and read.observed is observed and read.filters == filters
                        and not revision.stores_changed_since(read.revision)):
                    return None
                snapshot = service.views.viewer_snapshot(
                    worktree, show_stopped=filters[0], show_archived=filters[1])
                return revision, snapshot, SidebarModel.derive(snapshot), root_is_current(service.root)

            try:
                if self.sidebar_views:
                    # A shown sidebar acknowledges the painted native cursor
                    # first, so the counts read below already include it.
                    await app.mark_visible_thread_read()
                captured = await self.preparation.run_thread(capture)
            except (OSError, ValueError, CoordinationReadUnavailable, StaleRevision) as error:
                # An external writer is replacing or recovering the wire; the
                # next observed revision reads again.
                app.log.warning("Sidebar read interrupted", error)
                return
            if captured is None:
                continue
            revision, snapshot, derived, current = captured
            if self.observation is not observed or not current:
                continue
            notice = observed.sidebar.read_marker_notice
            tabs = app.open_tabs
            observed.sidebar.apply(snapshot, derived)
            self.sidebar_read = SidebarRead(observed, revision, filters)
            if snapshot.read_marker_notice and snapshot.read_marker_notice != notice:
                app.notify(snapshot.read_marker_notice, title="Read positions", severity="warning")
            if app.open_tabs != tabs:
                app.events.publish(OpenTabsChanged())

    def start(self) -> None:
        """One application revision observer serves visible views and roster paint."""
        from toad.constants import COMMS_REFRESH_INTERVAL

        self.timer = self.app.set_interval(COMMS_REFRESH_INTERVAL, self.refresh)
        self.refresh()

    async def close(self) -> None:
        if self.timer is not None:
            self.timer.stop()
        for task in (self.task, self.sidebar_task):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
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

    def refresh(self) -> None:
        if self.task is not None and not self.task.done():
            return
        self.task = asyncio.create_task(self.observe())

    async def observe(self) -> None:
        try:
            service = self.observed_service
            route_stamp = await self.preparation.run_thread(self.current_route_stamp)
            revision = await self.preparation.run_thread(service.views.revision) if service else None
            if (service is not None and service is self.observed_service and revision == self.revision
                    and route_stamp == self.route_stamp):
                return
        except (OSError, ValueError, RuntimeError):
            # A route publication may be replacing its marker. Its next revision
            # retries validation; no sidebar visibility can disable observation.
            return

        try:
            service = await self.preparation.run_thread(lambda: self.service)
            route_stamp = await self.preparation.run_thread(self.current_route_stamp)
            revision = await self.preparation.run_thread(service.views.revision)
            if not await self.preparation.run_thread(root_is_current, service.root):
                raise ValueError("Observed Comms route changed before publication")
            if (service is not self.observed_service
                    or await self.preparation.run_thread(self.current_route_stamp) != route_stamp):
                return
        except (OSError, ValueError, RuntimeError):
            # Invalidation must also reach mounted views when validation fails.
            # They retain their original read/route fence and show unavailable;
            # a change notification never certifies a presentation or a send.
            pass
        self.revision, self.route_stamp = revision, route_stamp
        self.events.publish(CoordinationObserved(revision))
        if self.sidebar_views:
            self.request_sidebar()

    def write(self, selected: RouteSelection, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. The existing
        # core route lock is held through the operation; no second lock/store.
        return run_selected_write(selected.root, operation, *args, implicit=selected.implicit, **kwargs)

